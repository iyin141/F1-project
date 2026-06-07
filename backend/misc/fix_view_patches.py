import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix Driver Standings Mock Targets
content = content.replace(
    'patch("api.drivers.repository.get_persisted_driver_standings"',
    'patch("api.drivers.views.get_persisted_driver_standings"'
)

# Fix Driver Standings Mock return values
content = content.replace(
    'return_value={"meta": {"year": 2024, "row_count": 0}, "data": []}',
    'return_value=[]'
)

# For test_driver_standings_endpoint_includes_readiness_when_service_returns_meta
# Mock currently returns a mocked_payload dict containing "meta" and "data".
content = re.sub(
    r'mocked_payload = \{\n\s+"meta": \{.*?\},\n\s+"data": \[(.*?)\]\n\s+\}',
    r'mocked_payload = [\1]',
    content,
    flags=re.DOTALL
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed view patches and mock values")
