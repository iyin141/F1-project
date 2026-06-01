"""
Django management command to sync F1 drivers from Jolpica.
# TODO: MOVE -> backend/api/sync_functions  # sync logic will be extracted; management command will call new functions

Usage:
    python manage.py sync_drivers --all                      # All seasons 1950–now
    python manage.py sync_drivers --year 2025                # Single season
    python manage.py sync_drivers --all --start 2000         # Partial range
    python manage.py sync_drivers                             # Current year only
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from api.sync_functions.sync_drivers import sync_season_drivers, sync_all_seasons


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
        if options["all"]:
            self.stdout.write(f"Syncing all seasons {options['start']}–{options['end']}...")
            result = sync_all_seasons(start=options["start"], end=options["end"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Total synced: {result.get('total_synced', 0)} | Errors: {result.get('total_errors', 0)}"
                )
            )
        else:
            year = options["year"]
            self.stdout.write(f"Syncing {year} season...")
            result = sync_season_drivers(year)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Year: {year} | Synced: {result.get('synced', 0)} | Errors: {result.get('errors', 0)}"
                )
            )
