import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# test_constructor_standings_endpoint_includes_message_when_empty
content = re.sub(
    r'(def test_constructor_standings_endpoint_includes_message_when_empty.*?response = self\.client\.get.*?self\.assertEqual\(response\.status_code, 200\)\s+)data = self\._parse_stream\(response\)',
    r'\1data = response.json()',
    content,
    flags=re.DOTALL
)

# test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable
content = re.sub(
    r'(def test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable.*?response = self\.client\.get.*?self\.assertEqual\(response\.status_code, 200\)\s+)data = self\._parse_stream\(response\)',
    r'\1data = response.json()',
    content,
    flags=re.DOTALL
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Reverted stream parser for constructor tests")
