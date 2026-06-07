import os
import importlib.util

migrations_dir = 'c:\\Users\\iyino\\Videos\\F1-project\\f1-project-backend\\backend\\api\\migrations'

print(f"Scanning {migrations_dir}")
print(f"Directory exists: {os.path.isdir(migrations_dir)}")
print(f"__init__.py exists: {os.path.isfile(os.path.join(migrations_dir, '__init__.py'))}")

files = os.listdir(migrations_dir)
py_files = [f for f in files if f.endswith('.py') and not f.startswith('__')]
print(f"\nFound {len(py_files)} migration files:")
for f in sorted(py_files):
    print(f"  {f}")

# Try to list migrations using pkgutil
print("\nTrying pkgutil.iter_modules:")
import pkgutil
import api.migrations
for importer, modname, ispkg in pkgutil.iter_modules(api.migrations.__path__):
    print(f"  {modname} (ispkg={ispkg})")

# Try to list using os.listdir on __path__
print(f"\napi.migrations.__path__: {api.migrations.__path__}")
