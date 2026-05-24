"""
Django management command to sync F1 drivers from Jolpica.

Usage:
    python manage.py sync_drivers --all                      # All seasons 1950–now
    python manage.py sync_drivers --year 2025                # Single season
    python manage.py sync_drivers --all --start 2000         # Partial range
    python manage.py sync_drivers                             # Current year only
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from api.drivers.services.sync_service import DriverSyncService


class Command(BaseCommand):
    help = "Sync F1 drivers from Jolpica into the DB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=datetime.now().year,
            help="Sync a specific season (default: current year)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Sync all seasons from --start to --end",
        )
        parser.add_argument(
            "--start",
            type=int,
            default=1950,
            help="Start year for --all sync (default: 1950)",
        )
        parser.add_argument(
            "--end",
            type=int,
            default=datetime.now().year,
            help="End year for --all sync (default: current year)",
        )

    def handle(self, *args, **options):
        service = DriverSyncService()

        if options["all"]:
            self.stdout.write(
                f"Syncing all seasons {options['start']}–{options['end']}..."
            )
            result = service.sync_all_seasons(
                start=options["start"],
                end=options["end"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Total synced: {result['total_synced']} | Errors: {result['total_errors']}"
                )
            )
        else:
            year = options["year"]
            self.stdout.write(f"Syncing {year} season...")
            result = service.sync_season_drivers(year)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Year: {year} | Synced: {result['synced']} | Errors: {result['errors']}"
                )
            )
