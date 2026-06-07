import os
import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Standings
content = content.replace(
    'patch("api.views.get_driver_standings",',
    'patch("api.drivers.views.get_persisted_driver_standings",'
)
content = content.replace(
    'patch("api.views.get_constructor_standings",',
    'patch("api.drivers.views.get_persisted_constructor_standings",'
)

# Unified Endpoints (Mock handle_data_request instead of extractors since we want to avoid SSE logic in simple tests)
# For weather:
content = re.sub(
    r'@patch\("api\.views\.WeatherExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)
# For pit stops:
content = re.sub(
    r'@patch\("api\.views\.PitStopExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)
# For incidents:
content = re.sub(
    r'@patch\("api\.views\.IncidentExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)
# For DRS:
content = re.sub(
    r'@patch\("api\.views\.DRSExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)
# For Track Status:
content = re.sub(
    r'@patch\("api\.views\.TrackStatusExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)
# For Telemetry:
content = re.sub(
    r'@patch\("api\.views\.TelemetryExtractor\.extract"\)',
    r'@patch("api.views.__init__.cache.get")',
    content
)

# Replace mock_extract.return_value with mock_extract.return_value = json.dumps(...)
# Wait, it's easier to just patch `api.views.__init__.nonblocking.handle_data_request` for the analysis laps test
content = content.replace(
    'patch("api.views.get_lap_analysis",',
    'patch("api.views.__init__.nonblocking.handle_data_request",'
)
content = content.replace(
    'with patch("api.views.__init__.nonblocking.handle_data_request", return_value=mocked_payload):',
    'from rest_framework.response import Response\n        with patch("api.views.__init__.nonblocking.handle_data_request", return_value=Response(mocked_payload, status=200)):',
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Applied quick fixes to test_api_endpoints.py")
