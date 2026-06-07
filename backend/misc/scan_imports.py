import sys
import os
import importlib
import pkgutil

# Add the backend root to the python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set django settings so imports work
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
import django
django.setup()

modules_to_test = [
    "api.drivers.views",
    "api.constructors.views",
    "api.results.views",
    "api.session.views",
    "api.schedule.views",
    "api.core.views", # if exists
]

print("Scanning view modules for import errors...")

errors = {}
for mod_name in modules_to_test:
    try:
        importlib.import_module(mod_name)
        print(f"[OK] {mod_name}")
    except Exception as e:
        errors[mod_name] = f"{type(e).__name__}: {e}"
        print(f"[ERROR] {mod_name} -> {type(e).__name__}: {e}")

if not errors:
    print("\nAll views imported successfully!")
else:
    print("\nFound errors in the following modules:")
    for mod, err in errors.items():
        print(f"  - {mod}: {err}")
