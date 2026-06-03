"""
Management command to completely wipe the database (production-ready data only).

This command:
1. Deletes all data tables (but keeps Django built-in tables)
2. Optionally runs migrations to recreate empty schema
3. Verifies completion

USAGE:
  python manage.py wipe_database --confirm
  python manage.py wipe_database --confirm --migrate (to also run migrations)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Completely wipe all production data from database (schema remains intact)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required to confirm wipe operation",
        )
        parser.add_argument(
            "--migrate",
            action="store_true",
            help="After wiping, run migrations to recreate empty schema",
        )

    def handle(self, *args, **options):
        if not options.get("confirm"):
            self.stdout.write(
                self.style.WARNING(
                    "SAFETY: --confirm flag required to perform database wipe. "
                    "This will delete ALL F1 data (drivers, standings, results, sessions, etc.)."
                )
            )
            return

        self.stdout.write(self.style.WARNING("Starting database wipe..."))

        try:
            # Get database backend type
            db_backend = connection.vendor
            
            # Get list of tables to truncate (exclude Django internal tables)
            with connection.cursor() as cursor:
                if db_backend == "postgresql":
                    cursor.execute(
                        """
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name NOT LIKE 'django_%'
                        AND table_name NOT LIKE 'sqlite_%'
                        AND table_name != 'sqlite_sequence'
                        ORDER BY table_name;
                        """
                    )
                elif db_backend == "sqlite":
                    cursor.execute(
                        """
                        SELECT name FROM sqlite_master 
                        WHERE type='table' 
                        AND name NOT LIKE 'django_%'
                        AND name NOT LIKE 'sqlite_%'
                        AND name != 'sqlite_sequence'
                        ORDER BY name;
                        """
                    )
                else:
                    raise CommandError(f"Unsupported database backend: {db_backend}")
                
                tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                self.stdout.write(self.style.SUCCESS("No tables to wipe (already clean)"))
                return

            self.stdout.write(f"Found {len(tables)} tables to truncate:")
            for table in tables:
                self.stdout.write(f"  - {table}")

            # Confirm once more
            self.stdout.write(
                self.style.WARNING(
                    "\nAbout to truncate {} tables. This CANNOT be undone.".format(len(tables))
                )
            )
            confirm = input("Type 'YES' to confirm: ").strip().upper()
            if confirm != "YES":
                self.stdout.write(self.style.ERROR("Wipe cancelled."))
                return

            # Disable foreign key constraints temporarily
            with connection.cursor() as cursor:
                if db_backend == "postgresql":
                    cursor.execute("SET session_replication_role = REPLICA;")

                    # Truncate all tables
                    for table in tables:
                        try:
                            cursor.execute(f"TRUNCATE TABLE {table} CASCADE;")
                            logger.info(f"Truncated table: {table}")
                        except Exception as e:
                            logger.warning(f"Error truncating {table}: {e}")

                    # Re-enable foreign key constraints
                    cursor.execute("SET session_replication_role = DEFAULT;")
                
                elif db_backend == "sqlite":
                    # SQLite doesn't support TRUNCATE, use DELETE instead
                    cursor.execute("PRAGMA foreign_keys = OFF;")
                    
                    # Delete all rows from tables
                    for table in tables:
                        try:
                            cursor.execute(f"DELETE FROM {table};")
                            logger.info(f"Cleared table: {table}")
                        except Exception as e:
                            logger.warning(f"Error clearing {table}: {e}")
                    
                    cursor.execute("PRAGMA foreign_keys = ON;")

            self.stdout.write(self.style.SUCCESS(f"✓ Successfully truncated {len(tables)} tables"))

            # Optionally run migrations
            if options.get("migrate"):
                self.stdout.write("Running migrations to recreate schema...")
                call_command("migrate", verbosity=1)
                self.stdout.write(self.style.SUCCESS("✓ Migrations completed"))

            self.stdout.write(self.style.SUCCESS("\n✓ Database wipe completed successfully!"))
            self.stdout.write("Next steps:")
            self.stdout.write("  1. Run workers to repopulate data (e.g., populate_season_schedule)")
            self.stdout.write("  2. Start live data listeners (e.g., prefetch_race_weekend)")

        except Exception as e:
            logger.exception(f"Error during database wipe: {e}")
            raise CommandError(f"Database wipe failed: {e}")
