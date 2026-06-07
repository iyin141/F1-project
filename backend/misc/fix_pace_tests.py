import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Replace get_pace_analysis with nonblocking.handle_data_request
content = re.sub(
    r'patch\("api\.views\.get_pace_analysis", return_value=(mocked_payload.*?)\)',
    r'patch("api.views.nonblocking.handle_data_request", return_value=Response(\1))',
    content
)

# For test_analysis_pace_endpoint_returns_400_for_invalid_session
# It shouldn't mock anything since the view handles it natively now.
content = content.replace(
    '        with patch("api.views.get_pace_analysis", side_effect=ValueError("session must be one of R, Q, FP1, FP2, FP3")):\n            response = self.client.get("/api/analysis/races/2024/1/pace/?session=FP4")',
    '        response = self.client.get("/api/analysis/races/2024/1/pace/?session=FP4")'
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed pace tests")
