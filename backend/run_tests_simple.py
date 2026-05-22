#!/usr/bin/env python
"""Simple test runner to verify Module C."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "manage.py", "test", "api.tests.unit", 
     "--settings=f1_project.settings_test", "--keepdb", "--noinput"],
    capture_output=True,
    text=True
)

# Print last 20 lines which should contain the summary
lines = result.stdout.split('\n') + result.stderr.split('\n')
print('\n'.join(lines[-20:]))

sys.exit(result.returncode)
