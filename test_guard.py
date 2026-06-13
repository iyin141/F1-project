import os
import django
import sys
from unittest.mock import patch, MagicMock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")
sys.path.append(os.path.join(os.getcwd(), 'backend'))

django.setup()

from django.test import RequestFactory
from api.session.views import AnalysisTelemetryAPIView

factory = RequestFactory()
request = factory.get('/api/v1/sessions/2010/1/race/telemetry?driver=VER&lap=1')
view = AnalysisTelemetryAPIView.as_view()

try:
    response = view(request, year=2010, round_number=1)
    print("Response Status:", response.status_code)
    print("Response Data:", response.data)
except Exception as e:
    print("Error:", str(e))
