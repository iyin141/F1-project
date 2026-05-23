"""
Django management command to create internal API key.

Usage:
    python manage.py create_internal_key
"""
from django.core.management.base import BaseCommand
from django.db import connection
from api.models.auth import APIKey


class Command(BaseCommand):
    help = "Create or retrieve internal API key for per-IP rate limiting"

    def handle(self, *args, **options):
        # Check if internal key already exists
        internal_keys = APIKey.objects.filter(tier="internal", is_active=True)
        
        if internal_keys.exists():
            key = internal_keys.first()
            self.stdout.write(
                self.style.WARNING(
                    f"Internal API key already exists:\n"
                    f"  Email: {key.email}\n"
                    f"  Key: {key.key}\n"
                    f"  ID: {key.id}\n"
                    f"\nAdd to .env: INTERNAL_API_KEY={key.key}"
                )
            )
            return
        
        # Create new internal key
        internal_key = APIKey.objects.create(
            email="internal@f1api.local",
            tier="internal",
            is_active=True,
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Internal API key created:\n"
                f"  Email: {internal_key.email}\n"
                f"  Tier: {internal_key.tier}\n"
                f"  Key UUID: {internal_key.key}\n"
                f"  ID: {internal_key.id}\n"
                f"\nAdd to .env file:\n"
                f"  INTERNAL_API_KEY={internal_key.key}\n"
                f"\nUse this key for internal requests and per-IP throttling testing.\n"
                f"Per-IP bucket: capacity=200, refill=2.0 tokens/sec, cost=1 per request"
            )
        )
