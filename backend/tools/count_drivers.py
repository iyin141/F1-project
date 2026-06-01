import os
import sys

# Ensure Django settings are available
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')

import django
django.setup()

from api.models.drivers import F1Driver

count = F1Driver.objects.count()
print('F1Driver count:', count)
# Print a few samples
for d in F1Driver.objects.all()[:10]:
    print(d.driver_id, d.code, d.given_name, d.family_name, d.seasons)
