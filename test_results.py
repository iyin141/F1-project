import os
import django
import sys
from unittest.mock import patch, MagicMock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")
sys.path.append(os.path.join(os.getcwd(), 'backend'))

django.setup()

from django.test import RequestFactory
from api.results.views.race import RaceResultsAPIView

factory = RequestFactory()
request = factory.get('/api/v1/sessions/2010/1/race/results')
view = RaceResultsAPIView.as_view()

try:
    response = view(request, year=2010, round_number=1)
    print("Response Status:", response.status_code)
    data = response.data
    readiness = data.get('readiness', {})
    print("Can Proceed:", readiness.get('can_proceed'))
    
    race_data = data.get('race', [])
    print(f"Loaded {len(race_data)} race results!")
    if len(race_data) > 0:
        print("Winner:", race_data[0].get('driver_name'), race_data[0].get('team'))
        
except Exception as e:
    print("Error:", str(e))
