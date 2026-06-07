import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the patch in test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable
content = content.replace(
    'with patch("api.views.nonblocking.handle_data_request", return_value=Response(mocked_payload)):',
    'with patch("api.views.get_constructor_standings", return_value=mocked_payload):'
)

# Wait, `get_driver_standings` might also have been messed up?
# Let's check if driver standings was changed.
content = content.replace(
    'with patch("api.views.nonblocking.handle_data_request", return_value=Response(mocked_driver_payload)):',
    'with patch("api.views.get_driver_standings", return_value=mocked_driver_payload):'
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Reverted constructor and driver patch modifications")
