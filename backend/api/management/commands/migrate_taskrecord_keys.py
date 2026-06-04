"""Management command to map legacy TaskRecord.task_key values to canonical keys.

Usage:
  python manage.py migrate_taskrecord_keys --dry-run --map-file=map.json
  python manage.py migrate_taskrecord_keys --apply --map-file=map.json

This command performs a conservative, non-destructive migration by default
(`--dry-run`). When `--apply` is provided it will create canonical TaskRecord
rows for keys that do not already exist, copying status/timestamps from the
original record. It does not delete or overwrite existing legacy rows.
"""
from __future__ import annotations

import json
from typing import List, Dict

from django.core.management.base import BaseCommand

from api.models.queue import TaskRecord


MAPPING_RULES = {
    # legacy prefix -> canonical prefix
    "populate_race_results": "race_results",
    "populate_positions": "positions",
    "populate_laps": "laps",
    "populate_drs": "drs",
    "populate_track_status": "track_status",
    "populate_pit_stops": "pit_stops",
    "populate_incidents": "incidents",
    "populate_weather": "weather",
    "populate_standings": "standings",
    # keyed formats
    "practice:": "practice_results:",
}


class Command(BaseCommand):
    help = "Migrate legacy TaskRecord.task_key values to canonical keys (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument("--apply", action="store_true", default=False)
        parser.add_argument("--map-file", type=str, default=None)

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False) or not options.get("apply", False)
        apply_changes = options.get("apply", False)
        map_file = options.get("map_file")

        self.stdout.write(self.style.MIGRATE_HEADING("Scanning TaskRecord rows for legacy keys..."))

        results: List[Dict] = []

        # Sort prefixes by length desc so longer matches are preferred
        prefixes = sorted(MAPPING_RULES.keys(), key=lambda x: -len(x))

        for tr in TaskRecord.objects.all():
            old = tr.task_key
            new = old
            for p in prefixes:
                if old.startswith(p):
                    new = old.replace(p, MAPPING_RULES[p], 1)
                    break

            if new != old:
                results.append({
                    "old": old,
                    "new": new,
                    "status": tr.status,
                    "created_at": tr.created_at.isoformat() if tr.created_at else None,
                    "started_at": tr.started_at.isoformat() if tr.started_at else None,
                    "completed_at": tr.completed_at.isoformat() if tr.completed_at else None,
                })

                if apply_changes:
                    # Create canonical row if it does not exist
                    defaults = {
                        "status": tr.status,
                        "error_message": tr.error_message,
                        "started_at": tr.started_at,
                        "completed_at": tr.completed_at,
                    }
                    obj, created = TaskRecord.objects.get_or_create(task_key=new, defaults=defaults)
                    if created:
                        self.stdout.write(self.style.SUCCESS(f"Created canonical TaskRecord: {new} (from {old})"))

        summary = {
            "total_scanned": TaskRecord.objects.count(),
            "mapped_count": len(results),
        }

        self.stdout.write(self.style.MIGRATE_LABEL(f"Found {summary['mapped_count']} legacy keys out of {summary['total_scanned']} TaskRecord rows."))

        if map_file:
            with open(map_file, "w", encoding="utf-8") as f:
                json.dump({"summary": summary, "mappings": results}, f, indent=2)
            self.stdout.write(self.style.NOTICE(f"Wrote mapping report to {map_file}"))

        if dry_run and not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run mode: no DB changes applied. Use --apply to create canonical rows."))
        else:
            self.stdout.write(self.style.SUCCESS("Migration completed."))
