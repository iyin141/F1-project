import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Insert helper function
helper_code = """
    def _parse_stream(self, response):
        import json
        content = b"".join(response.streaming_content).decode("utf-8")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # If it's a fallback string format?
            return json.loads(content.split("\\n\\n")[0].replace("data: ", ""))
"""

content = content.replace(
    "class ApiEndpointTests(TestDefaultAPIKeyMixin, TestCase):",
    "class ApiEndpointTests(TestDefaultAPIKeyMixin, TestCase):" + helper_code
)

# 2. Replace response.json() with self._parse_stream(response) for the specific failing tests
# test_driver_standings_endpoint_includes_message_when_empty
content = re.sub(
    r'(def test_driver_standings_endpoint_includes_message_when_empty.*?response = self\.client\.get.*?self\.assertEqual\(response\.status_code, 200\)\s+)data = response\.json\(\)',
    r'\1data = self._parse_stream(response)',
    content,
    flags=re.DOTALL
)

# test_constructor_standings_endpoint_includes_message_when_empty
content = re.sub(
    r'(def test_constructor_standings_endpoint_includes_message_when_empty.*?response = self\.client\.get.*?self\.assertEqual\(response\.status_code, 200\)\s+)data = response\.json\(\)',
    r'\1data = self._parse_stream(response)',
    content,
    flags=re.DOTALL
)

# test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable
content = re.sub(
    r'(def test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable.*?response = self\.client\.get.*?self\.assertEqual\(response\.status_code, 200\)\s+)data = response\.json\(\)',
    r'\1data = self._parse_stream(response)',
    content,
    flags=re.DOTALL
)


with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Injected _parse_stream into test_api_endpoints.py")
