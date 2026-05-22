#!/usr/bin/env python
"""Test Module E imports."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.getcwd())
django.setup()

# Test imports
try:
    from api.views.registration import RegisterAPIView, VerifyEmailAPIView, RevokeAPIKeyView
    print("✓ Registration views imported successfully")
except Exception as e:
    print(f"✗ Failed to import registration views: {e}")
    sys.exit(1)

try:
    from api.tasks import (
        send_verification_email,
        send_welcome_email,
        send_tier_upgrade_email,
        send_rate_limit_warning_email,
        send_key_revocation_email,
        send_monthly_usage_report,
    )
    print("✓ Registration tasks imported successfully (6 tasks)")
except Exception as e:
    print(f"✗ Failed to import registration tasks: {e}")
    sys.exit(1)

# Test URL configuration
try:
    from django.urls import reverse
    reverse('register')
    print("✓ Registration URLs registered")
except Exception as e:
    print(f"✗ Failed to verify registration URLs: {e}")
    sys.exit(1)

print("\n✓ Module E imports and configuration verified successfully!")
