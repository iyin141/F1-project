import os
from pathlib import Path
import re

BASE_DIR = Path(r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend")

# Files to target: all python files
for root, dirs, files in os.walk(BASE_DIR):
    if "venv" in root or ".pytest_cache" in root or "__pycache__" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = Path(root) / file
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Replace specific imports
                new_content = content.replace("api.core.task_status", "api.core.task_status")
                new_content = new_content.replace("api.core.task_management", "api.core.task_management")
                new_content = new_content.replace("api.core.registration", "api.core.registration")
                new_content = new_content.replace("api.core.cache_decorators", "api.core.cache_decorators")
                
                # Also handle from api.views import ... where the imported thing is from the module?
                # Actually, `from api.core import task_status` would be an issue.
                new_content = re.sub(r'from api\.views import (task_status|task_management|registration|cache_decorators)', r'from api.core import \1', new_content)
                new_content = re.sub(r'from api\.views\.(task_status|task_management|registration|cache_decorators)', r'from api.core.\1', new_content)

                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"Updated imports in {path}")
            except Exception as e:
                print(f"Error processing {path}: {e}")
