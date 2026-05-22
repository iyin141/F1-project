#!/usr/bin/env python
"""Test Module D imports."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.getcwd())
django.setup()

# Test imports
try:
    from api.auth import APIKeyAuthentication
    print("✓ APIKeyAuthentication imported successfully")
except Exception as e:
    print(f"✗ Failed to import APIKeyAuthentication: {e}")
    sys.exit(1)

try:
    from api.throttling import APIKeyThrottle
    print("✓ APIKeyThrottle imported successfully")
except Exception as e:
    print(f"✗ Failed to import APIKeyThrottle: {e}")
    sys.exit(1)

try:
    from api.common.mixins import RateLimitHeadersMixin
    print("✓ RateLimitHeadersMixin imported successfully")
except Exception as e:
    print(f"✗ Failed to import RateLimitHeadersMixin: {e}")
    sys.exit(1)

# Test that settings is correctly configured
try:
    from django.conf import settings
    assert 'api.auth.APIKeyAuthentication' in settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']
    print("✓ APIKeyAuthentication configured in REST_FRAMEWORK")
except Exception as e:
    print(f"✗ REST_FRAMEWORK config error: {e}")
    sys.exit(1)

try:
    assert 'api.throttling.APIKeyThrottle' in settings.REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES']
    print("✓ APIKeyThrottle configured in REST_FRAMEWORK")
except Exception as e:
    print(f"✗ REST_FRAMEWORK throttle config error: {e}")
    sys.exit(1)

print("\n✓ Module D imports and configuration verified successfully!")
