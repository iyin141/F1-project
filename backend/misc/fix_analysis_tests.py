import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Make sure Response is imported if it's not already
if "from rest_framework.response import Response" not in content:
    content = "from rest_framework.response import Response\n" + content

# Replace return_value=mocked_payload with return_value=Response(mocked_payload) in the handle_data_request patches
content = re.sub(
    r'patch\("api\.views\.nonblocking\.handle_data_request", return_value=(mocked_payload.*?)\)',
    r'patch("api.views.nonblocking.handle_data_request", return_value=Response(\1))',
    content
)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed handle_data_request patches to return Response")
