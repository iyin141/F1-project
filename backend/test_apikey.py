#!/usr/bin/env python
"""Quick test of APIKey model."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from api.models import APIKey

# Create an APIKey
key = APIKey.objects.create(email='test@example.com', tier='pro')
print(f"✓ APIKey created: {key.email} (ID: {key.id}, Key: {key.key}, Tier: {key.tier})")

# Test mark_used
key.mark_used()
print(f"✓ After mark_used: request_count={key.request_count}, last_used_at={key.last_used_at}")

# Clean up
key.delete()
print("✓ APIKey deleted successfully")
print("✓ Module C verification complete!")
