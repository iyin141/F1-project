"""
Shared utility helpers for the F1 API service layer.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone as dt_timezone

from django.utils import timezone

logger = logging.getLogger(__name__)


def is_current_year(year: int) -> bool:
    """
    Return True if *year* is the current calendar year or later.

    Used to gate background-persistence tasks: standings and schedule
    are never enqueued for the current year — they are always served live.
    """
    return int(year) >= timezone.now().year


def is_round_completed(year: int, round_number: int) -> bool:
    """
    Return True if the race for this round has already taken place.

    Uses SeasonSchedule.payload to determine completion from the race date.
    Date resolution order:
      1. ``date`` field (YYYY-MM-DD string from EventDate)
      2. ``session5_date_utc`` field (ISO 8601 UTC string for the race session)

    Falls back to False (treat as live) in all error cases — missing schedule,
    missing date fields, parse errors — to ensure we never serve stale data.

    Unlike is_current_year(), this is round-level not year-level, so a
    completed Round 1 2026 is safely persisted even while Round 10 2026 is live.
    """
    try:
        from api.services.persistence import get_persisted_race_by_round

        race = get_persisted_race_by_round(int(year), int(round_number))
        if not race:
            logger.warning(
                "event=round_completion_check year=%s round=%s result=false reason=no_schedule",
                year, round_number,
            )
            return False

        # Primary: plain date string stored as YYYY-MM-DD
        date_str = race.get("date") or race.get("race_date")
        if date_str:
            race_date = date.fromisoformat(str(date_str)[:10])
            return race_date < timezone.now().date()

        # Fallback: race session datetime stored as ISO 8601 UTC
        session5_utc = race.get("session5_date_utc")
        if session5_utc:
            race_dt = datetime.strptime(
                str(session5_utc)[:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=dt_timezone.utc)
            return race_dt < timezone.now()

        logger.warning(
            "event=round_completion_check year=%s round=%s result=false reason=no_date",
            year, round_number,
        )
        return False

    except Exception as exc:
        logger.warning(
            "event=round_completion_check year=%s round=%s result=false error=%s",
            year, round_number, exc,
        )
        return False
