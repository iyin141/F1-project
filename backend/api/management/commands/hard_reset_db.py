"""
Management command to perform a hard reset of the Neon PostgreSQL database.

This command:
1. Deletes all data from all registered Django models via ORM
2. Drops all tables in the public schema using raw SQL
3. Leaves database schema-less and empty (ready for `python manage.py migrate`)

USAGE:
  python manage.py hard_reset_db --confirm --production

SAFETY:
- Requires --confirm flag AND manual "YES" prompt to prevent accidents
- Only works with Neon PostgreSQL (checks database vendor)
- Respects Django connection management
"""

from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import connection, connections
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Perform hard reset of Neon PostgreSQL database (drops all tables, deletes all data)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required to confirm hard reset operation",
        )
        parser.add_argument(
            "--production",
            action="store_true",
            help="Acknowledge this is production database",
        )

    def handle(self, *args, **options):
        if not options.get("confirm"):
            self.stdout.write(
                self.style.WARNING(
                    "SAFETY: --confirm flag required. This will DELETE ALL DATA from Neon database."
                )
            )
            return

        if not options.get("production"):
            self.stdout.write(
                self.style.WARNING(
                    "SAFETY: --production flag required to acknowledge production database."
                )
            )
            return

        # Verify database vendor
        db_vendor = connection.vendor
        if db_vendor != "postgresql":
            raise CommandError(
                f"This command only works with PostgreSQL. Current database: {db_vendor}"
            )

        self.stdout.write(
            self.style.WARNING(
                f"⚠️  HARD RESET: Will delete ALL data from {connection.settings_dict.get('NAME', 'unknown')} "
                f"on {connection.settings_dict.get('HOST', 'unknown')}"
            )
        )

        # Double confirmation
        confirm = input('Type "YES" to permanently delete all data: ').strip().upper()
        if confirm != "YES":
            self.stdout.write(self.style.ERROR("Hard reset cancelled."))
            return

        try:
            self.stdout.write("Starting hard reset...")

            # Step 1: Delete all data via Django ORM
            self._delete_via_orm()

            # Step 2: Drop all remaining tables
            self._drop_all_tables()

            # Step 3: Verify empty database
            self._verify_empty()

            self.stdout.write(
                self.style.SUCCESS(
                    "\n✓ Hard reset completed successfully!"
                )
            )
            self.stdout.write("Next steps:")
            self.stdout.write("  1. Run: python manage.py migrate")
            self.stdout.write("  2. Run worker tasks to seed data")

        except Exception as e:
            logger.exception(f"Error during hard reset: {e}")
            raise CommandError(f"Hard reset failed: {e}")

    def _delete_via_orm(self):
        """Delete all data from all models via Django ORM."""
        self.stdout.write("Step 1: Deleting data from all models via ORM...")

        models = list(apps.get_models())
        deleted_count = 0

        for model in models:
            try:
                count = model.objects.count()
                if count > 0:
                    model.objects.all().delete()
                    deleted_count += count
                    logger.info(f"Deleted {count} records from {model._meta.label}")
            except Exception as e:
                logger.warning(
                    f"Could not delete from {model._meta.label}: {e} (may be system model)"
                )

        self.stdout.write(f"  ✓ Deleted {deleted_count} records from models")

    def _drop_all_tables(self):
        """Drop all tables in the public schema."""
        self.stdout.write("Step 2: Dropping all tables in public schema...")

        with connection.cursor() as cursor:
            # Get all tables
            cursor.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """
            )
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                self.stdout.write("  ✓ No tables to drop (database already empty)")
                return

            self.stdout.write(f"  Found {len(tables)} tables to drop:")
            for table in tables:
                self.stdout.write(f"    - {table}")

            # Drop all tables with CASCADE
            for table in tables:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
                    logger.info(f"Dropped table: {table}")
                except Exception as e:
                    logger.warning(f"Error dropping {table}: {e}")

        self.stdout.write(f"  ✓ Dropped {len(tables)} tables")

    def _verify_empty(self):
        """Verify database is completely empty."""
        self.stdout.write("Step 3: Verifying database is empty...")

        with connection.cursor() as cursor:
            # Check tables
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE';
                """
            )
            table_count = cursor.fetchone()[0]

            # Check sequences
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.sequences 
                WHERE sequence_schema = 'public';
                """
            )
            sequence_count = cursor.fetchone()[0]

        if table_count == 0 and sequence_count == 0:
            self.stdout.write("  ✓ Database is completely empty")
            logger.info(f"Verification passed: {table_count} tables, {sequence_count} sequences")
        else:
            raise CommandError(
                f"Database verification failed: {table_count} tables, {sequence_count} sequences remain"
            )
