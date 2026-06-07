import django
django.setup()
from django.db.migrations.loader import MigrationLoader

loader = MigrationLoader(None)
print("Available migrations for 'api':")
if 'api' in loader.migrated_apps:
    print(f"  Migrated app found: api")
    api_migrations = [k for k in loader.disk_migrations.keys() if k[0] == 'api']
    print(f"  Disk migrations count: {len(api_migrations)}")
    for migration_key in sorted(api_migrations)[-5:]:  # Last 5
        print(f"    {migration_key}")
else:
    print("  'api' not in migrated_apps")
    print(f"  Migrated apps: {loader.migrated_apps}")

print("\nAll disk migrations apps:")
apps_with_migrations = set(k[0] for k in loader.disk_migrations.keys())
for app in sorted(apps_with_migrations):
    print(f"  {app}")

print("\nMigration graph info:")
try:
    print(f"  leaf_nodes: {loader.graph.leaf_nodes()}")
except Exception as e:
    print(f"  Error getting leaf nodes: {e}")
