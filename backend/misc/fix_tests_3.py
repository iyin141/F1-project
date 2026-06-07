import os
import re

file1 = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_analysis_workers.py"

with open(file1, 'r', encoding='utf-8') as f:
    content = f.read()

# Pace analysis
content = re.sub(
    r"'session_median_lap_seconds': 95\.5",
    r"'session_median_lap_seconds': 95.5, 'laps_completed': 50",
    content
)

# Stint analysis
content = re.sub(
    r"'lap_end': 30,",
    r"'lap_end': 30,\n                    'total_laps': 30,",
    content
)

# Sector analysis
content = re.sub(
    r"'theoretical_best_lap_seconds': 93\.666,",
    r"'theoretical_best_lap_seconds': 93.666,\n                    'laps_count': 10,",
    content
)

# Tyre strategy
content = re.sub(
    r"'total_laps': (\d+),",
    r"'laps_in_stint': \1,",
    content
)

with open(file1, 'w', encoding='utf-8') as f:
    f.write(content)


file2 = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_workers.py"

with open(file2, 'r', encoding='utf-8') as f:
    content2 = f.read()

# Laps analysis (is_personal_best, compound, pit_status)
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


with open(file2, 'w', encoding='utf-8') as f:
    f.write(content2)

print("Fixed mock data attributes in tests!")
