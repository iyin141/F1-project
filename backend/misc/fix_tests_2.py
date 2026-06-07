import os
import re

files = [
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_analysis_workers.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\tests\unit\test_tier3_workers.py"
]

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if limit_max is already there to avoid duplicates
    if "'limit_max': 1000" not in content:
        # We need to replace any 'can_proceed': True, 'row_count': X} with 'can_proceed': True, 'row_count': X, 'limit_max': 1000}
        content = re.sub(
            r"'can_proceed': True, 'row_count': (\d+)\}",
            r"'can_proceed': True, 'row_count': \1, 'limit_max': 1000}",
            content
        )
        
        # Also just in case there are still some without row_count
        content = re.sub(
            r"'can_proceed': True\}",
            r"'can_proceed': True, 'row_count': 2, 'limit_max': 1000}",
            content
        )
        
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)

print("Fixed row_count and limit_max in meta dicts.")
