import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix mocked_payload missing 'can_proceed' and 'message' for the empty test
empty_meta_replacement = '"meta": {"year": 2024, "round": 1, "session": "R", "row_count": 0, "limit_max": 2000, "can_proceed": False, "message": "No data"}'
content = re.sub(
    r'"meta": \{"year": 2024, "round": 1, "session": "R", "row_count": 0, "limit_max": 2000\}',
    empty_meta_replacement,
    content,
    count=1
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed mocked payload in test_api_endpoints.py")
