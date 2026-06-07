import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Replace any patch of "api.views.get_*" with patch of "api.views.nonblocking.handle_data_request"
content = re.sub(
    r'patch\("api\.views\.get_[a-zA-Z0-9_]+", return_value=(mocked_payload.*?)\)',
    r'patch("api.views.nonblocking.handle_data_request", return_value=Response(\1))',
    content
)

# And if there are any remaining `patch("api.views.nonblocking.handle_data_request", return_value=mocked_payload)`
# which don't have Response, wrap them
content = re.sub(
    r'patch\("api\.views\.nonblocking\.handle_data_request", return_value=(mocked_payload(?!.*?Response).*?)\)',
    r'patch("api.views.nonblocking.handle_data_request", return_value=Response(\1))',
    content
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed all remaining analysis mock tests")
