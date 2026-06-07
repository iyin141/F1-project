import re

FILE = "api/views/__init__.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Replace only exactly `session_name = request.query_params.get("session", "R")`
# when it's on a line by itself (with leading whitespace)

def replacer(match):
    indent = match.group(1)
    return f'{indent}session_name = request.query_params.get("session", "R")\n{indent}if session_name not in ["R", "Q", "S", "SQ", "FP1", "FP2", "FP3"]:\n{indent}    return Response({{"error": "session must be one of R, Q, FP1, FP2, FP3"}}, status=400)'

content = re.sub(r'^([ \t]+)session_name = request\.query_params\.get\("session", "R"\)\s*$', replacer, content, flags=re.MULTILINE)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Added session validation safely")
