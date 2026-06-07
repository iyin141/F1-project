import re

# Fix test_tier3_analysis_workers.py
file1 = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_analysis_workers.py"
with open(file1, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(
    r"'lap_end': 20,",
    r"'lap_end': 20,\n                    'total_laps': 20,",
    content
)
content = re.sub(
    r"'lap_end': 57,",
    r"'lap_end': 57,\n                    'total_laps': 37,",
    content
)

with open(file1, 'w', encoding='utf-8') as f:
    f.write(content)

# Fix test_tier3_workers.py
file2 = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_workers.py"
with open(file2, 'r', encoding='utf-8') as f:
    content2 = f.read()

# Make sure all laps have 'is_personal_best', 'compound', 'pit_status'
# The missing one is inside test_populate_laps_structure_includes_pace_data probably
content2 = re.sub(
    r"'time_seconds': 95\.5",
    r"'time_seconds': 95.5, 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none'",
    content2
)
content2 = re.sub(
    r"'time_seconds': 94\.2",
    r"'time_seconds': 94.2, 'is_personal_best': True, 'compound': 'MEDIUM', 'pit_status': 'none'",
    content2
)
content2 = re.sub(
    r"'lap': 1, 'driver_code': 'VER', 'time_seconds': 96\.1\}",
    r"'lap': 1, 'driver_code': 'VER', 'time_seconds': 96.1, 'is_personal_best': False, 'compound': 'SOFT', 'pit_status': 'none'}",
    content2
)

with open(file2, 'w', encoding='utf-8') as f:
    f.write(content2)

print("Fixed mock data attributes in tests!")
