"""
Shared utility helpers for the F1 API service layer.
"""
from __future__ import annotations

from django.utils import timezone


def is_current_year(year: int) -> bool:
    """
    Return True if *year* is the current calendar year or later.

    Used to gate background-persistence tasks: analysis, telemetry, and unified
    session data are never enqueued for the current year — they are always served
    live per the persistence spec.
    """
    return int(year) >= timezone.now().year
