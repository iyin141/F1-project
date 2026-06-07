import os
import ast
from pathlib import Path

BASE_DIR = Path(r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend")
API_DIR = BASE_DIR / "api"
SERIALIZERS_PATH = API_DIR / "serializers.py"

with open(SERIALIZERS_PATH, "r", encoding="utf-8") as f:
    source = f.read()

tree = ast.parse(source)

classes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        classes.append(node.name)

print("Total classes:", len(classes))
print("Classes:", classes)
