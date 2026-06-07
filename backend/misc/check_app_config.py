import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from django.apps import apps

print("Installed apps:")
for app in apps.get_app_configs():
    print(f"  {app.name} (label: {app.label})")
    if app.label == 'api':
        print(f"    module: {app.module}")
        print(f"    migrations_module: {app.migrations_module}")
        print(f"    has_migrations: {app.migrations_module is not None}")
        
        # Try to import the migrations module directly
        try:
            import api.migrations
            print(f"    api.migrations module: {api.migrations}")
            import pkgutil
            import api.migrations as api_migs
            for importer, modname, ispkg in pkgutil.iter_modules(api_migs.__path__):
                print(f"      - {modname}")
        except Exception as e:
            print(f"    Error importing api.migrations: {e}")
