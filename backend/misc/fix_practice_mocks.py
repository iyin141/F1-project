import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix practice session endpoint test
content = content.replace(
    'with patch("api.views.get_practice_session_results", return_value=mocked_practice_payload):',
    'with patch("api.results.views.handle_data_request", return_value=Response(mocked_practice_payload)):'
)

# Fix qualifying endpoint test
content = content.replace(
    'with patch("api.results.views.get_persisted_qualifying_results", return_value=[]):',
    'with patch("api.results.views.handle_data_request", return_value=Response({"qualifying": [], "readiness": {"can_proceed": False}})):'
)

# Fix race results readiness test
content = content.replace(
    'with patch("api.results.views.get_persisted_race_results", return_value=[]):',
    'with patch("api.results.views.handle_data_request", return_value=Response({"race": [], "readiness": {"can_proceed": False}})):'
)
content = content.replace(
    'with patch("api.results.views.get_persisted_qualifying_results", return_value=[]):',
    'pass'
)


with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed results mock targets")
