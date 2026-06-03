import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from django.db.migrations.loader import MigrationLoader
import logging

# Enable debug logging to see what's happening
logging.basicConfig(level=logging.DEBUG)

print("Creating MigrationLoader...")
try:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    print("Loader created")
    
    print(f"\nMigrated apps: {loader.migrated_apps}")
    
    print("\n API app migrations:")
    api_migs = [(k, v) for k, v in loader.disk_migrations.items() if k[0] == 'api']
    print(f"  Found {len(api_migs)} API migrations on disk")
    for key in sorted(api_migs)[-3:]:
        print(f"    {key}")
    
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
