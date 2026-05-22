#!/usr/bin/env python
"""Run Module D test verification."""
import os
import sys
import django
import subprocess

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings_test')
sys.path.insert(0, os.getcwd())

# Run tests
result = subprocess.run(
    [sys.executable, "manage.py", "test", "api.tests.unit", 
     "--settings=f1_project.settings_test", "--keepdb", "--noinput"],
    capture_output=True,
    text=True,
    timeout=120
)

# Extract summary lines
lines = (result.stdout + result.stderr).split('\n')
summary_started = False
for line in lines:
    if 'Ran ' in line or 'FAILED' in line or 'OK' in line or 'FAIL:' in line:
        summary_started = True
    if summary_started:
        print(line)
        
sys.exit(result.returncode)
