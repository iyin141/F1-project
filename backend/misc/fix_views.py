import re

file_path = r'c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\views.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern for bare excepts inside finally blocks replacing pass with logger
pattern = re.compile(r'(except Exception:\s+)pass', re.MULTILINE)

new_content = pattern.sub(r'\1logger.warning("Failed to release lock or clear cache")', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Replaced passes in views.py")
