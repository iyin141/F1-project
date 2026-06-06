"""Management command to sync F1 champions from Jolpica."""
from django.core.management.base import BaseCommand
from api.drivers.services.champions_sync_service import ChampionsSyncService


class Command(BaseCommand):
    help = "Sync all-time F1 champions from Jolpica into F1Champion table"

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            default=None,
            help='Sync a single year only'
        )
        parser.add_argument(
            'years',
            nargs='*',
            type=int,
            help='Sync specific years (e.g., 2010 2026 to sync range 2010-2026)'
        )

    def handle(self, *args, **options):
        service = ChampionsSyncService()

        # Handle year range from positional arguments
        if options['years']:
            if len(options['years']) == 2:
                start_year, end_year = options['years']
                self.stdout.write(f"Syncing champions {start_year}–{end_year}...")
                synced, errors = 0, 0
                for year in range(start_year, end_year + 1):
                    result = service.sync_year_champion(year)
                    if result.get('synced'):
                        synced += 1
                        self.stdout.write(self.style.SUCCESS(f"  ✓ {year}: {result.get('driver_id', 'N/A')}"))
                    else:
                        errors += 1
                        self.stdout.write(self.style.WARNING(f"  ✗ {year}"))
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Done. Synced: {synced} | Errors: {errors}"
                ))
            else:
                self.stdout.write(self.style.ERROR("Please provide start and end years (e.g., 2010 2026)"))
        elif options['year']:
            year = options['year']
            result = service.sync_year_champion(year)
            if result.get('synced'):
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Synced {year}: {result['driver_id']}"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"✗ No champion data for {year}"
                ))
        else:
            self.stdout.write("Syncing all champions 1950–2026...")
            result = service.sync_all_champions()
            self.stdout.write(self.style.SUCCESS(
                f"Done. Synced: {result['total_synced']} | "
                f"Errors: {result['total_errors']} | "
                f"Coverage: {result['years_covered']}"
            ))
