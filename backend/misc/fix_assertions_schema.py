import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix practice test assertions
content = content.replace(
    'self.assertEqual(payload["session"], "FP1")',
    'self.assertEqual(payload["meta"]["session"], "FP1")'
)
content = content.replace(
    'self.assertEqual(payload["practice"], [])',
    'self.assertEqual(payload["data"], [])'
)
content = content.replace(
    'self.assertIsNotNone(payload["readiness"])',
    'self.assertIn("can_proceed", payload["meta"])'
)
content = content.replace(
    'self.assertFalse(payload["readiness"]["can_proceed"])',
    'self.assertFalse(payload["meta"]["can_proceed"])'
)

# Fix qualifying test assertions
content = content.replace(
    'self.assertEqual(payload["qualifying"], [])',
    'self.assertEqual(payload["data"], [])'
)

# Fix race test assertions
content = content.replace(
    'self.assertIn("readiness", payload)',
    'self.assertIn("can_proceed", payload["meta"])'
)

# Fix the mock payloads in fix_practice_mocks.py that we added earlier
content = content.replace(
    'return_value=Response({"qualifying": [], "readiness": {"can_proceed": False}})',
    'return_value=Response({"meta": {"can_proceed": False}, "data": []})'
)
content = content.replace(
    'return_value=Response({"race": [], "readiness": {"can_proceed": False}})',
    'return_value=Response({"meta": {"can_proceed": False}, "data": []})'
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed assertions for new schema")
