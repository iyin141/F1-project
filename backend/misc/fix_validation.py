import re

FILE = "api/views/__init__.py"

with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Add validation check
validation_code = """
            if session_name not in ["R", "Q", "S", "SQ", "FP1", "FP2", "FP3"]:
                return Response({"error": "session must be one of R, Q, FP1, FP2, FP3"}, status=400)
"""

content = content.replace('session_name = request.query_params.get("session", "R")', 'session_name = request.query_params.get("session", "R")' + validation_code)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Added session validation to views")
