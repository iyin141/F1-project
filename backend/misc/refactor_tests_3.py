import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Revert handle_data_request patch path
content = content.replace(
    'api.views.__init__.handle_data_request',
    'api.views.__init__.nonblocking.handle_data_request'
)

# And also revert results views
content = content.replace(
    'api.results.views.handle_data_request',
    'api.results.views.nonblocking.handle_data_request'
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Reverted fix 3 to test_api_endpoints.py")
