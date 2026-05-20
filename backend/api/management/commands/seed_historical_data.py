"""
Django management command: Seed historical F1 data into PostgreSQL.

Phase 6: Eliminates cold loads for 5 years of historical static data.

Usage:
    python manage.py seed_historical_data --years 2020,2021,2022,2023,2024
    python manage.py seed_historical_data --years 2024,2023,2022,2021,2020 (reverse chron, default)
    python manage.py seed_historical_data --year-range 2020-2024
    python manage.py seed_historical_data --quick (last 1 year only)
"""
from __future__ import annotations

import logging
from typing import Optional, List
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now as django_now

from api.services.seeding import (
    dispatch_season_seed_batch,
    wait_for_seed_batch,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed historical F1 data (2020-2024) into PostgreSQL and Redis for warm cache"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            type=str,
            help='Comma-separated years to seed (e.g., 2024,2023,2022,2021,2020)',
        )
        parser.add_argument(
            '--year-range',
            type=str,
            help='Year range to seed (e.g., 2020-2024)',
        )
        parser.add_argument(
            '--quick',
            action='store_true',
            help='Quick seed: last 1 year only',
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Wait for seed batch to complete before returning',
        )
        parser.add_argument(
            '--max-tasks',
            type=int,
            default=0,
            help='Max tasks to dispatch (0 = no limit)',
        )
    
    def handle(self, *args, **options):
        """Main command handler."""
        # Determine which seasons to seed
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
                f"[SeedHistorical] Starting seed batch for years: {years}"
            )
        )
        
        try:
            # Dispatch seeding for each year
            task_ids = dispatch_season_seed_batch(
                years=years,
                max_tasks=options['max_tasks'],
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"[SeedHistorical] Dispatched {len(task_ids)} tasks to backfill queue"
                )
            )
            
            # Optionally wait for completion
            if options['wait']:
                self.stdout.write(
                    self.style.WARNING(
                        "[SeedHistorical] Waiting for seed batch to complete..."
                        " (this may take 30–60 minutes)"
                    )
                )
                completed, failed = wait_for_seed_batch(task_ids)
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[SeedHistorical] Seed batch complete: "
                        f"{completed} completed, {failed} failed"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "[SeedHistorical] Seeding running in background. "
                        "Check logs and task status endpoints to monitor progress."
                    )
                )
        
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"[SeedHistorical] Error: {exc}")
            )
            raise CommandError(str(exc))
    
    def _parse_years(self, options: dict) -> List[int]:
        """Parse year arguments from command options."""
        if options['quick']:
            # Last 1 year only
            from datetime import datetime
            current_year = datetime.now().year
            return [current_year]
        
        if options['years']:
            try:
                return [int(y.strip()) for y in options['years'].split(',')]
            except ValueError:
                raise CommandError("Invalid --years format (expected: 2024,2023,...)")
        
        if options['year_range']:
            try:
                start, end = options['year_range'].split('-')
                start, end = int(start.strip()), int(end.strip())
                # Return in reverse chronological order (most recent first)
                return list(range(end, start - 1, -1))
            except (ValueError, AttributeError):
                raise CommandError("Invalid --year-range format (expected: 2020-2024)")
        
        return []
