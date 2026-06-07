import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix __init__ patches
content = content.replace(
    'api.views.__init__.nonblocking.handle_data_request',
    'api.views.nonblocking.handle_data_request'
)

# And fix results views nonblocking too
# Wait, for results views, it is `from api.services.nonblocking import handle_data_request`
# So in `api.results.views`, it is `api.results.views.handle_data_request`!
# Let me replace `api.results.views.nonblocking.handle_data_request` with `api.results.views.handle_data_request`
content = content.replace(
    'api.results.views.nonblocking.handle_data_request',
    'api.results.views.handle_data_request'
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Applied fix 4 to test_api_endpoints.py")
