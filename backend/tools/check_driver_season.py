import os
import django
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from api.drivers.views import DriverSeasonAPIView

factory = APIRequestFactory()
request = factory.get('/api/drivers/hamilton/2019/', HTTP_X_API_KEY='e6b9d79e-f8b3-4276-a3a9-f8bf4e398dc2')
response = DriverSeasonAPIView.as_view()(request, driver_code='hamilton', year=2019)

import pprint
pprint.pprint({
    'status': response.status_code,
    'driver_code': response.data.get('driver_code'),
    'can_proceed': response.data.get('readiness', {}).get('can_proceed'),
    'total_races': response.data.get('total_races'),
})
