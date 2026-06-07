import os

TEST_FILE = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Replace simple function mocks
content = content.replace('"api.views.get_season_schedule"', '"api.schedule.views.get_season_schedule"')
content = content.replace('"api.views.get_race_by_round"', '"api.schedule.views.get_race_by_round"')
content = content.replace('"api.views.get_constructor_standings"', '"api.constructors.views.get_constructor_standings"')
content = content.replace('"api.views.get_stint_analysis"', '"api.session.views.get_stint_analysis"')
content = content.replace('"api.views.get_telemetry_snapshot"', '"api.session.views.get_telemetry_snapshot"')
content = content.replace('"api.views.stream_unified_full_session_json"', '"api.session.views.stream_unified_full_session_json"')

# Handle remaining handle_data_request patches
content = content.replace('"api.views.nonblocking.handle_data_request"', '"api.session.views.handle_data_request"')

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Test file updated successfully!")
