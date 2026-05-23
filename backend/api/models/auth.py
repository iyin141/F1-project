"""
API authentication models — Phase 6a.

APIKey model for tier-based rate limiting and usage tracking.
"""
from __future__ import annotations

import uuid
from django.db import models
from django.utils import timezone


class APIKey(models.Model):
    """
    API key for tier-based authentication and rate limiting.
    
    Each key is associated with an email, a tier (controlling rate limits),
    usage tracking (request count), and audit fields (created_at, last_used_at).
    """
    
    TIER_CHOICES = [
        ("free", "Free"),
        ("standard", "Standard"),
        ("premium", "Premium"),
        ("internal", "Internal"),
    ]
    
    # Primary key: UUID
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Email: unique, required
    email = models.EmailField(unique=True, db_index=True)
    
    # API key: UUID, unique
    key = models.UUIDField(unique=True, db_index=True, default=uuid.uuid4, editable=False)
    
    # Tier: controls rate limit bucket
    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default="free",
        db_index=True,
    )
    
    # Active flag: soft-delete via is_active=False
    is_active = models.BooleanField(default=True, db_index=True)
    
    # Audit timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    
    # Usage tracking: incremented per request
    request_count = models.BigIntegerField(default=0)
    
    class Meta:
        db_table = "api_apikey"
        indexes = [
            models.Index(fields=["email", "is_active"]),
            models.Index(fields=["tier", "is_active"]),
        ]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
    
    def __str__(self) -> str:
        return f"APIKey {self.email} ({self.tier})"
    
    def mark_used(self) -> None:
        """Update last_used_at to now and increment request count."""
        self.last_used_at = timezone.now()
        self.request_count += 1
        self.save(update_fields=["last_used_at", "request_count"])
