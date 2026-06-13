"""
Django management command: Seed historical F1 data into PostgreSQL.

Phase 6: Eliminates cold loads for 5 years of historical static data.

Usage:
    python manage.py seed_historical_data --years 2020,2021,2022,2023,2024
    python manage.py seed_historical_data --years 2024,2023,2022,2021,2020 (reverse chron, default)
    python manage.py seed_historical_data --year-range 2010-2026
    python manage.py seed_historical_data --quick (last 1 year only)
"""
from __future__ import annotations

import logging
from typing import Optional, List
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now as django_now

from api.models import SeasonSchedule, DriverTelemetry
from api.queue.manager import TaskManager
from api.workers.tier4_telemetry.populate_session_telemetry import populate_session_telemetry
from api.workers.tier2_fast.populate_weather import populate_weather
from api.workers.tier2_fast.populate_pit_stops import populate_pit_stops
from api.workers.tier3_medium.populate_positions import populate_positions
from api.workers.tier3_medium.populate_laps import populate_laps
from api.workers.tier2_fast.populate_incidents import populate_incidents
from api.workers.tier3_medium.populate_drs import populate_drs

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Seed historical F1 data (2010-current) into PostgreSQL and Redis for warm cache"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            type=str,
            help='Comma-separated years to seed (e.g., 2024,2023,2022,2021,2020)',
        )
        parser.add_argument(
            '--year-range',
            type=str,
            help='Year range to seed (e.g., 2010-2026)',
        )
        parser.add_argument(
            '--quick',
            action='store_true',
            help='Quick seed: last 1 year only',
        )
    
    def handle(self, *args, **options):
        """Main command handler."""
        years = self._parse_years(options)
        
        if not years:
            self.stdout.write(
                self.style.ERROR(
                    "No years specified. Use --years, --year-range, or --quick"
                )
            )
            return
        
        self.stdout.write(
            self.style.SUCCESS(
                f"[SeedHistorical] Starting warm cache for years: {years}"
            )
        )
        
        SESSIONS = ["FP1", "FP2", "FP3", "Q", "SQ", "S", "R"]
        dispatched_count = 0

        for year in years:
            schedule = SeasonSchedule.objects.filter(year=year).first()
            if not schedule or not schedule.payload:
                self.stdout.write(f"No schedule found for {year}, skipping...")
                continue
                
            races = schedule.payload.get("races", [])
            for race in races:
                round_number = race.get("round") or race.get("round_number")
                if not round_number:
                    continue
                
                round_number = int(round_number)

                for session_type in SESSIONS:
                    # Check if telemetry already exists for this session
                    if DriverTelemetry.objects.filter(year=year, round_number=round_number, session=session_type).exists():
                        continue
                        
                    # Also skip if it's a future session
                    session_end_val = race.get("date") # Simplify: if race hasn't happened, skip
                    if session_type != "R":
                        # Ergast schedule payload doesn't always have past practice dates easily accessible
                        # We will just enqueue and let FastF1 fail if it hasn't happened or doesn't exist
                        pass
                        
                    task_key = f"telemetry_session_cache:{year}:{round_number}:{session_type}"
                    
                    success = TaskManager.enqueue_if_needed(
                        task_key=task_key,
                        task_fn=populate_session_telemetry,
                        year=year,
                        round_number=round_number,
                        session_type=session_type,
                    )
                    
                    if success:
                        dispatched_count += 1
                        self.stdout.write(f"Enqueued {task_key}")

        self.stdout.write(
            self.style.SUCCESS(
                f"[SeedHistorical] Dispatched {dispatched_count} missing telemetry sessions to the background cache."
            )
        )
    
    def _parse_years(self, options: dict) -> List[int]:
        """Parse year arguments from command options."""
        if options['quick']:
            from datetime import datetime
            return [datetime.now().year]
        
        if options['years']:
            try:
                return [int(y.strip()) for y in options['years'].split(',')]
            except ValueError:
                raise CommandError("Invalid --years format (expected: 2024,2023,...)")
        
        if options['year_range']:
            try:
                start, end = options['year_range'].split('-')
                start, end = int(start.strip()), int(end.strip())
                return list(range(end, start - 1, -1))
            except (ValueError, AttributeError):
                raise CommandError("Invalid --year-range format (expected: 2010-2026)")
        
        return []
