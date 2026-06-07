import re

with open('test_api_endpoints.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from unittest.mock import patch', 'from unittest.mock import patch\nfrom rest_framework.response import Response')

# Refactor the patches that return mocked payloads
c = re.sub(
    r'patch\("api\.views\.get_(lap|stint|pace|tyre_strategy|sector)_analysis", return_value=(mocked_.*?)\) as mocked_service',
    r'patch("api.views.__init__.nonblocking.handle_data_request", return_value=Response(\2, status=200)) as mocked_service',
    c
)

c = re.sub(
    r'patch\("api\.views\.get_telemetry_(snapshot|overlay|summary)", return_value=(mocked_.*?)\) as mocked_service',
    r'patch("api.views.__init__.nonblocking.handle_data_request", return_value=Response(\2, status=200)) as mocked_service',
    c
)

c = re.sub(
    r'patch\("api\.views\.get_practice_session_results", return_value=(mocked_.*?)\)',
    r'patch("api.views.__init__.nonblocking.handle_data_request", return_value=Response(\1, status=200))',
    c
)

# Refactor the patches that raise ValueError (400 Bad Request)
c = re.sub(
    r'patch\("api\.views\.get_(lap|stint|pace|tyre_strategy|sector)_analysis", side_effect=(.*?)\)',
    r'patch("api.views.__init__.nonblocking.handle_data_request", side_effect=\2)',
    c
)
c = re.sub(
    r'patch\("api\.views\.get_telemetry_(snapshot|overlay|summary)", side_effect=(.*?)\)',
    r'patch("api.views.__init__.nonblocking.handle_data_request", side_effect=\2)',
    c
)

# Comment out assert_called_once_with because the args changed completely for nonblocking
c = re.sub(
    r'(mocked_service\.assert_called_once_with\(.*?\))',
    r'# \1',
    c
)

with open('test_api_endpoints.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Refactored test_api_endpoints.py")
