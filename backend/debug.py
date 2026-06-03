import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from django.db.migrations.loader import MigrationLoader
from django.apps import apps

# Get the api app config
api_app = apps.get_app_config('api')
print(f"API App Config:")
print(f"  name: {api_app.name}")
print(f"  label: {api_app.label}")

# Try to manually import the migrations module
print(f"\nTrying to import api.migrations...")
try:
    import api.migrations
    print(f"  SUCCESS: {api.migrations}")
except Exception as e:
    print(f"  ERROR: {e}")

# Check if Django can discover the migrations module
print(f"\nDjango's module_has_submodule check:")
from django.utils.module_loading import module_has_submodule
print(f"  api.module_has_submodule(migrations): {module_has_submodule(api_app.module, 'migrations')}")

# Check what Django's MigrationLoader sees
print(f"\nMigrationLoader analysis:")
loader = MigrationLoader(None, ignore_no_migrations=True)
print(f"  migrated_apps: {loader.migrated_apps}")
print(f"  'api' in migrated_apps: {'api' in loader.migrated_apps}")

# List all apps that have migrations
all_migrated = {app for app, _ in loader.disk_migrations.keys()}
print(f"  Apps with migrations on disk: {all_migrated}")
