import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# test_driver_standings_endpoint_includes_readiness_when_service_returns_meta
replacement = 'patch("api.drivers.views.stream_task_result_json", return_value=Response(mocked_payload, status=200)), patch("api.drivers.views.TaskManager.enqueue_if_needed")'
content = content.replace('patch("api.drivers.views.TaskManager.enqueue_if_needed")', replacement)

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Applied stream_task_result_json mock to all driver standings tests")
