import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Fix handle_data_request patch path
content = content.replace(
    'api.views.__init__.nonblocking.handle_data_request',
    'api.views.__init__.handle_data_request'
)

# For results views
content = content.replace(
    'api.results.views.nonblocking.handle_data_request',
    'api.results.views.handle_data_request'
)

# Add TaskManager patch for Standings tests
# We want to replace `@patch("api.drivers.repository.get_persisted_driver_standings")` with
# `@patch("api.drivers.views.TaskManager.enqueue_if_needed")`
# `@patch("api.drivers.repository.get_persisted_driver_standings")`
content = re.sub(
    r'(\s*)with patch\("api\.drivers\.views\.get_persisted_driver_standings"(.*):\n',
    r'\1with patch("api.drivers.views.TaskManager.enqueue_if_needed"), patch("api.drivers.repository.get_persisted_driver_standings"\2:\n',
    content
)
# Note: I originally replaced with api.drivers.views.get_persisted_driver_standings! It should be repository!
content = content.replace(
    'api.drivers.views.get_persisted_driver_standings',
    'api.drivers.repository.get_persisted_driver_standings'
)
content = content.replace(
    'api.drivers.views.get_persisted_constructor_standings',
    'api.drivers.repository.get_persisted_constructor_standings'
)

# Also fix the `api.views.__init__.cache.get` mock to not cause side effects if the test doesn't provide a mock
# Wait, for the cache.get patch:
content = content.replace(
    '@patch("api.views.__init__.cache.get")',
    '@patch("django.core.cache.cache.get")'
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Applied fix 2 to test_api_endpoints.py")
