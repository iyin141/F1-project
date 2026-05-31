from __future__ import annotations

"""
Django management command to wipe persisted data used during local development.

Actions performed (unless skipped via flags):
- Clear all configured Django caches
- Delete all rows for selected JSONB/persisted models
- Attempt to purge Celery queued tasks and remove celerybeat schedule files
- Delete local `f1_cache` directory (recursive)
- Remove the sqlite DB file for the default DB (and related -wal/-shm files)

Flags:
--no-cache   : skip clearing Django caches
--no-files   : skip removing files/directories (f1_cache, schedule files)
--no-sqlite  : skip deleting sqlite DB file
"""

import glob
import logging
import os
import shutil
from typing import List, Optional

from django.apps import apps
from django.conf import settings
from django.core.cache import caches
from django.core.management.base import BaseCommand
from django.db import connections


LOGGER = logging.getLogger("wipe_persisted_data")

# Models to wipe (model class names). We'll search across installed apps.
MODEL_NAMES: List[str] = [
    "SeasonSchedule",
    "RaceResultData",
    "QualifyingResultData",
    "PracticeResultData",
    "DriverLapAnalysis",
    "DriverTelemetry",
    "SessionData",
    "DriverStandings",
    "ConstructorStandings",
    "DriverCareer",
    "DriverSeasonBreakdown",
    "TaskRecord",
]


def _get_base_dir() -> str:
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir:
        try:
            return os.path.abspath(str(base_dir))
        except Exception:
            pass
    # fallback to current working directory
    return os.path.abspath(os.getcwd())


def _find_model(model_name: str):
    """
    Try to locate a model class by name. Prefer the 'api' app, otherwise search all apps.
    Returns model class or None.
    """
    try:
        return apps.get_model("api", model_name)
    except Exception:
        # search across all apps
        for app_config in apps.get_app_configs():
            try:
                model = app_config.get_model(model_name)
                if model:
                    return model
            except LookupError:
                continue
            except Exception:
                # unexpected; log and continue
                LOGGER.exception("Error while searching for model %s in app %s", model_name, app_config.name)
                continue
    return None


class Command(BaseCommand):
    help = "Wipe caches, persisted JSONB model rows, celery tasks, f1_cache, and sqlite DB file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-cache", action="store_true", dest="no_cache", help="Skip clearing Django caches"
        )
        parser.add_argument(
            "--no-files", action="store_true", dest="no_files", help="Skip deleting files (f1_cache, celerybeat schedules)"
        )
        parser.add_argument(
            "--no-sqlite", action="store_true", dest="no_sqlite", help="Skip deleting the sqlite DB file if used"
        )

    def handle(self, *args, **options):
        self.verbosity = int(options.get("verbosity", 1))
        self.no_cache = bool(options.get("no_cache", False))
        self.no_files = bool(options.get("no_files", False))
        self.no_sqlite = bool(options.get("no_sqlite", False))

        # Ensure logging at least to stdout for immediate feedback
        if not LOGGER.handlers:
            handler = logging.StreamHandler(self.stdout)
            handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)

        LOGGER.info("Starting wipe_persisted_data command")
        self.stdout.write("wipe_persisted_data: start")

        base_dir = _get_base_dir()
        LOGGER.debug("Determined base dir: %s", base_dir)

        # 1) Clear caches
        if self.no_cache:
            LOGGER.info("Skipping cache clear (--no-cache)")
            self.stdout.write("Skipping cache clear")
        else:
            try:
                cache_aliases = getattr(settings, "CACHES", {}).keys()
                if not cache_aliases:
                    # still attempt the default cache
                    cache_aliases = ["default"]
                for alias in cache_aliases:
                    try:
                        caches[alias].clear()
                        LOGGER.info("Cleared cache alias: %s", alias)
                        self.stdout.write(f"Cleared cache: {alias}")
                    except Exception:
                        LOGGER.exception("Failed to clear cache alias: %s", alias)
                        self.stderr.write(f"Failed to clear cache alias: {alias}")
            except Exception:
                LOGGER.exception("Unexpected error while clearing caches")
                self.stderr.write("Unexpected error while clearing caches")

        # 2) Delete persisted JSONB model rows
        try:
            LOGGER.info("Deleting persisted rows for configured models")
            for model_name in MODEL_NAMES:
                try:
                    model = _find_model(model_name)
                    if model is None:
                        LOGGER.warning("Model not found: %s; skipping", model_name)
                        self.stdout.write(f"Model not found: {model_name}; skipping")
                        continue
                    # Count rows (best-effort)
                    try:
                        count = model.objects.count()
                    except Exception:
                        count = None
                    # Delete all rows
                    try:
                        deleted = model.objects.all().delete()
                        # deleted is a tuple (n_deleted, {<model_label>: n, ...})
                        self.stdout.write(f"Deleted rows for {model_name}: {deleted[0] if isinstance(deleted, tuple) else deleted}")
                        LOGGER.info("Deleted rows for %s: %s", model_name, deleted)
                    except Exception:
                        LOGGER.exception("Failed to delete rows for model %s", model_name)
                        self.stderr.write(f"Failed to delete rows for model {model_name}")
                except Exception:
                    LOGGER.exception("Unexpected error handling model %s", model_name)
                    self.stderr.write(f"Unexpected error handling model {model_name}")
        except Exception:
            LOGGER.exception("Unexpected error during model row deletions")
            self.stderr.write("Unexpected error during model row deletions")

        # 3) Attempt to purge celery tasks and remove schedule files
        try:
            purged_count: Optional[int] = None
            try:
                # Attempt to import celery current_app and purge
                from celery import current_app as celery_app  # type: ignore

                try:
                    purged_count = celery_app.control.purge()
                    LOGGER.info("Celery purge requested; purged approximately %s tasks", purged_count)
                    self.stdout.write(f"Celery purge requested; purged approximately {purged_count} tasks")
                except Exception:
                    LOGGER.exception("Error while calling celery.control.purge()")
                    self.stderr.write("Error while calling celery.control.purge()")
            except Exception:
                LOGGER.debug("Celery not available or import failed; skipping celery purge")

            # Remove celerybeat schedule files if present (look recursively under base_dir)
            try:
                pattern = os.path.join(base_dir, "**", "celerybeat-schedule*")
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    for schedule_path in matches:
                        try:
                            if os.path.isfile(schedule_path):
                                os.remove(schedule_path)
                                LOGGER.info("Removed celery schedule file: %s", schedule_path)
                                self.stdout.write(f"Removed celery schedule file: {schedule_path}")
                        except Exception:
                            LOGGER.exception("Failed to remove schedule file: %s", schedule_path)
                            self.stderr.write(f"Failed to remove schedule file: {schedule_path}")
                else:
                    LOGGER.debug("No celerybeat-schedule files found under %s", base_dir)
            except Exception:
                LOGGER.exception("Error while searching/removing celerybeat-schedule files")
                self.stderr.write("Error while searching/removing celerybeat-schedule files")
        except Exception:
            LOGGER.exception("Unexpected error during celery purge step")
            self.stderr.write("Unexpected error during celery purge step")

        # 4) Delete f1_cache directory and other local files (unless skipped)
        if self.no_files:
            LOGGER.info("Skipping file deletions (--no-files)")
            self.stdout.write("Skipping file deletions")
        else:
            try:
                # Look for directories named 'f1_cache' under base_dir and cwd (recursive)
                inspected_roots = {base_dir, os.getcwd()}
                found_any = False
                for root in inspected_roots:
                    pattern = os.path.join(root, "**", "f1_cache")
                    for candidate in glob.glob(pattern, recursive=True):
                        if os.path.isdir(candidate):
                            found_any = True
                            try:
                                shutil.rmtree(candidate)
                                LOGGER.info("Removed f1_cache directory: %s", candidate)
                                self.stdout.write(f"Removed f1_cache directory: {candidate}")
                            except Exception:
                                LOGGER.exception("Failed to remove f1_cache directory: %s", candidate)
                                self.stderr.write(f"Failed to remove f1_cache directory: {candidate}")
                if not found_any:
                    LOGGER.debug("No f1_cache directory found under %s or cwd", base_dir)

                # Additionally, remove celerybeat-schedule* files directly in base_dir and cwd (non-recursive)
                for root in inspected_roots:
                    try:
                        for schedule_path in glob.glob(os.path.join(root, "celerybeat-schedule*")):
                            if os.path.isfile(schedule_path):
                                try:
                                    os.remove(schedule_path)
                                    LOGGER.info("Removed schedule file: %s", schedule_path)
                                    self.stdout.write(f"Removed schedule file: {schedule_path}")
                                except Exception:
                                    LOGGER.exception("Failed to remove schedule file: %s", schedule_path)
                                    self.stderr.write(f"Failed to remove schedule file: {schedule_path}")
                    except Exception:
                        LOGGER.exception("Error while cleaning schedule files under %s", root)
            except Exception:
                LOGGER.exception("Unexpected error during file deletion step")
                self.stderr.write("Unexpected error during file deletion step")

        # 5) Remove sqlite DB file if default DB is sqlite and not skipped
        if self.no_sqlite:
            LOGGER.info("Skipping sqlite DB removal (--no-sqlite)")
            self.stdout.write("Skipping sqlite DB removal")
        else:
            try:
                default_db = getattr(settings, "DATABASES", {}).get("default", {})
                engine = str(default_db.get("ENGINE", "")).lower()
                if "sqlite" in engine:
                    db_name = default_db.get("NAME")
                    if not db_name or str(db_name).strip() in ("", ":memory:"):
                        LOGGER.info("Default sqlite DB is in-memory or unnamed; nothing to delete")
                        self.stdout.write("Default sqlite DB is in-memory or unnamed; nothing to delete")
                    else:
                        # Determine candidate paths to check for the DB file
                        candidates: List[str] = []
                        db_name_str = str(db_name)
                        if os.path.isabs(db_name_str):
                            candidates.append(db_name_str)
                        else:
                            candidates.append(os.path.join(base_dir, db_name_str))
                            candidates.append(os.path.join(os.getcwd(), db_name_str))
                            candidates.append(db_name_str)  # relative path as-is
                        # ensure uniqueness and normalize
                        candidates = [os.path.abspath(p) for p in dict.fromkeys(candidates)]
                        removed_any = False
                        # Close DB connections so file isn't locked (especially on Windows)
                        try:
                            connections.close_all()
                        except Exception:
                            LOGGER.exception("Error while closing DB connections before removing sqlite file")
                        for path in candidates:
                            try:
                                if os.path.isfile(path):
                                    try:
                                        os.remove(path)
                                        removed_any = True
                                        LOGGER.info("Removed sqlite DB file: %s", path)
                                        self.stdout.write(f"Removed sqlite DB file: {path}")
                                    except Exception:
                                        LOGGER.exception("Failed to remove sqlite DB file: %s", path)
                                        self.stderr.write(f"Failed to remove sqlite DB file: {path}")
                                    # attempt to remove associated -wal/-shm files
                                    for suffix in ("-wal", "-shm", "-journal"):
                                        aux = f"{path}{suffix}"
                                        try:
                                            if os.path.isfile(aux):
                                                os.remove(aux)
                                                LOGGER.info("Removed sqlite auxiliary file: %s", aux)
                                                self.stdout.write(f"Removed sqlite auxiliary file: {aux}")
                                        except Exception:
                                            LOGGER.exception("Failed to remove sqlite auxiliary file: %s", aux)
                                else:
                                    LOGGER.debug("No sqlite DB file at: %s", path)
                            except Exception:
                                LOGGER.exception("Error while checking/removing sqlite DB candidate: %s", path)
                        if not removed_any:
                            LOGGER.info("No sqlite DB file removed; none of the candidates existed")
                            self.stdout.write("No sqlite DB file removed; none of the candidates existed")
                else:
                    LOGGER.info("Default DB engine is not sqlite; skipping sqlite file removal")
                    self.stdout.write("Default DB engine is not sqlite; skipping sqlite file removal")
            except Exception:
                LOGGER.exception("Unexpected error during sqlite DB removal step")
                self.stderr.write("Unexpected error during sqlite DB removal step")

        LOGGER.info("wipe_persisted_data: completed")
        self.stdout.write("wipe_persisted_data: completed")
