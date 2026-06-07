import re

TEST_FILE = "api/tests/unit/test_api_endpoints.py"

with open(TEST_FILE, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("from django.test import TestCase", "from django.test import TestCase\nfrom rest_framework.response import Response")

with open(TEST_FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("Added Response import to top")
