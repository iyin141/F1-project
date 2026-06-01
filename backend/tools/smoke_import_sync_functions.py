import sys, os
root = r'c:\Users\iyino\Videos\F1-project\f1-project-backend\backend'
if root not in sys.path:
    sys.path.insert(0, root)

# Ensure Django settings are configured so model imports succeed
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings_test')
import django
django.setup()

import importlib
modules = ['api.sync_functions.sync_drivers', 'api.sync_functions.sync_champions']
for m in modules:
    mod = importlib.import_module(m)
    print('imported', m, 'ok')
print('smoke-import OK')
