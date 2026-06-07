import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'api.drivers.repository.get_persisted_constructor_standings',
    'api.views.get_constructor_standings'
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed constructor standings patch")
