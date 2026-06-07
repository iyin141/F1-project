import re

FILE = "api/tests/unit/test_api_endpoints.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Replace any remaining patch("api.views.get_practice_session_results")
content = re.sub(
    r'with patch\("api\.views\.get_practice_session_results", return_value=(.*?)\):',
    r'with patch("api.results.views.handle_data_request", return_value=Response({"meta": {"session": "FP1", "can_proceed": True}, "data": \1})):',
    content
)

# Wait, the `mocked_practice` was likely a list, but the new standard expects a dictionary if I'm returning it directly from Response.
# Wait, let's see what `test_practice_endpoint_returns_practice_payload` does.
# I will just write a script to rewrite those specific tests because regex might get complicated.
