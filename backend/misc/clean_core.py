import os

filepath = r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\core\__init__.py"

with open(filepath, "r", encoding="utf-8") as f:
    lines = f.readlines()

# We only want lines up to line 158 (index 157)
new_lines = lines[:158]

# And we want to remove the broken imports from lines 12 to 73
# Lines 12 to 73 in 1-index is index 11 to 72

final_lines = []
for i, line in enumerate(new_lines):
    # Skip the massive broken block of imports
    if 11 <= i <= 72:
        continue
    final_lines.append(line)

with open(filepath, "w", encoding="utf-8") as f:
    f.writelines(final_lines)

print("Core __init__.py cleaned!")
