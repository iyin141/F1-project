#!/usr/bin/env python
"""Simple test to verify Module C - just run tests and show summary."""
import os
import sys
import django

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings_test')
sys.path.insert(0, os.getcwd())
django.setup()

# Import test runner
from django.test.utils import get_runner
from django.conf import settings

TestRunner = get_runner(settings)
test_runner = TestRunner(keepdb=True, verbosity=2)

# Run tests
failures = test_runner.run_tests(["api.tests.unit"])

# Print summary
if failures == 0:
    print("\n" + "="*70)
    print("✓ MODULE C VERIFICATION SUCCESSFUL - ALL TESTS PASSED")
    print("="*70)
else:
    print("\n" + "="*70)
    print(f"✗ {failures} TEST(S) FAILED")
    print("="*70)

sys.exit(failures)
