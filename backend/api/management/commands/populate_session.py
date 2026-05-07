"""Populate full SessionData (weather, pit_stops, incidents, positions, drs, track_status)."""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import SessionData
from api.services.fastf1_runtime import fastf1
from api.services.store import store_session_data
from api.services.unified_service import (
    DRSExtractor,
    IncidentExtractor,
    PitStopExtractor,
    PositionExtractor,
    TrackStatusExtractor,
    WeatherExtractor,
)

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}

# (key_name, extractor_class, extra_kwargs)
_EXTRACTOR_SPECS = [
    ("weather", WeatherExtractor, {}),
    ("pit_stops", PitStopExtractor, {}),
    ("incidents", IncidentExtractor, {}),
    ("positions", PositionExtractor, {}),
    ("drs", DRSExtractor, {}),
    ("track_status", TrackStatusExtractor, {}),
]

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Populate SessionData for one round/session (weather, pit_stops, incidents, "
        "positions, drs, track_status). Merges keys into an existing row if present."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, required=True, dest="round_number", help="Round number, e.g. 5")
        parser.add_argument(
            "--session",
            type=str,
            default="R",
            help="Session type: R (default), Q, FP1, FP2, FP3, S, SQ",
        )
        parser.add_argument(
            "--only",
            type=str,
            default=None,
            help="Comma-separated subset of keys to populate, e.g. 'weather,pit_stops'. Default: all.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing keys in the payload even if already present",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options["year"]
        round_number = options["round_number"]
        session_type = str(options["session"]).upper()
        force = options["force"]
        only_raw = options.get("only")
        logger.info("event=command_started command=populate_session year=%s round=%s session=%s force=%s", year, round_number, session_type, force)

        if session_type not in _ALLOWED_SESSIONS:
            raise CommandError(
                f"Invalid session type: {session_type}. Must be one of {sorted(_ALLOWED_SESSIONS)}."
            )

        # Resolve which keys to populate
        if only_raw:
            requested_keys = {k.strip().lower() for k in only_raw.split(",")}
            valid_keys = {spec[0] for spec in _EXTRACTOR_SPECS}
            unknown = requested_keys - valid_keys
            if unknown:
                raise CommandError(
                    f"Unknown keys in --only: {sorted(unknown)}. Valid keys: {sorted(valid_keys)}."
                )
            specs = [s for s in _EXTRACTOR_SPECS if s[0] in requested_keys]
        else:
            specs = _EXTRACTOR_SPECS

        # Check which keys already exist unless --force
        if not force:
            existing = SessionData.objects.filter(
                year=year, round_number=round_number, session=session_type
            ).first()
            existing_keys = set((existing.payload or {}).keys()) if existing else set()
            new_specs = [s for s in specs if s[0] not in existing_keys]
            skipped = [s[0] for s in specs if s[0] in existing_keys]
            if skipped:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping already-present keys (use --force to overwrite): {skipped}"
                    )
                )
            specs = new_specs

        if not specs:
            self.stdout.write(self.style.WARNING("Nothing to populate — all requested keys already present."))
            return

        # Load FastF1 session once (heavy)
        self.stdout.write(f"Loading FastF1 session year={year} round={round_number} session={session_type}…")
        try:
            session = fastf1.get_session(year, round_number, session_type)
            session.load(telemetry=False, weather=True, messages=True)
        except Exception as exc:
            raise CommandError(f"Failed to load FastF1 session: {exc}")

        # Run each extractor and collect results by key name
        data_dict: dict[str, list] = {}
        for key, extractor_cls, extra_kwargs in specs:
            self.stdout.write(f"  Extracting {key}…")
            try:
                extractor = extractor_cls(
                    session=session,
                    year=year,
                    round_number=round_number,
                    session_type=session_type,
                )
                result = extractor.extract(**extra_kwargs)
                rows = result.get("data", [])
                data_dict[key] = rows
                self.stdout.write(f"    → {len(rows)} rows")
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"    ⚠ {key} extraction failed: {exc} — skipping key")
                )

        if not data_dict:
            self.stdout.write(self.style.WARNING("No data extracted — nothing stored."))
            return

        # Merge into SessionData (store_session_data handles merge)
        record = store_session_data(year, round_number, session_type, data_dict)

        stored_keys = sorted(data_dict.keys())
        total_rows = sum(len(v) for v in data_dict.values())
        logger.info("event=command_completed command=populate_session year=%s round=%s session=%s keys=%s total_rows=%s", year, round_number, session_type, stored_keys, total_rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Populated SessionData year={year} round={round_number} session={session_type} | "
                f"keys={stored_keys} total_rows={total_rows}"
            )
        )
