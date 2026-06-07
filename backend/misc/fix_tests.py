import os
import re

files = [
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_analysis_workers.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_workers.py"
]

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace the meta dictionaries that miss row_count
    content = re.sub(
        r"'meta': \{'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True\}",
        r"'meta': {'year': 2023, 'round': 4, 'session': 'R', 'can_proceed': True, 'row_count': 2}",
        content
    )
    
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)

print("Fixed row_count in meta dicts.")
