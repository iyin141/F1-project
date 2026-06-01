import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
import django
django.setup()

from api.drivers.repository import resolve_to_jolpica_id
from api.models.drivers import F1Driver

print('resolve_to_jolpica_id("hamilton", 2021) ->', resolve_to_jolpica_id('hamilton', 2021))
print('F1Driver objects filter driver_id__icontains=hamilton:')
for d in F1Driver.objects.filter(driver_id__icontains='hamilton'):
    print(d.driver_id, d.code, d.given_name, d.family_name, d.seasons)

print('F1Driver objects filter family_name__iexact="Hamilton":')
for d in F1Driver.objects.filter(family_name__iexact='Hamilton'):
    print(d.driver_id, d.code, d.given_name, d.family_name, d.seasons)
