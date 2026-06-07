import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# I want to specifically change test_constructor_standings_endpoint_includes_message_when_empty
# back to assertFalse.

def replace_constructor_assert(match):
    return match.group(0).replace('self.assertTrue(data["readiness"]["can_proceed"])', 'self.assertFalse(data["readiness"]["can_proceed"])')

content = re.sub(
    r'def test_constructor_standings_endpoint_includes_message_when_empty.*?def test_constructor_standings_endpoint_returns_non_blocking_readiness_when_unavailable',
    replace_constructor_assert,
    content,
    flags=re.DOTALL
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed constructor assertion")
