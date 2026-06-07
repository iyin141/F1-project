#!/usr/bin/env python
"""
Direct migration applicator - bypasses manage.py command line
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from django.core.management import call_command
from django.db.migrations.executor import MigrationExecutor
from django.db import DEFAULT_DB_ALIAS, connections

# Get executor
executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])

# Check planned migrations
plan = executor.migration_plan([('api', '0023_remove_sessiondata_idx_sd_year_round_and_more')])
print(f"Migration plan to execute:")
for migration, backwards in plan:
    print(f"  {'← (reverse)' if backwards else '→'} {migration}")

if plan:
    print("\nApplying migrations...")
    try:
        # Execute all pending migrations
        call_command('migrate', 'api', verbosity=2)
        print("\nMigration applied successfully!")
    except Exception as e:
        print(f"Error applying migration: {e}")
        import traceback
        traceback.print_exc()
else:
    print("No migrations to apply")

# Check final status
print("\nFinal migration status:")
call_command('showmigrations', 'api', verbosity=0)
