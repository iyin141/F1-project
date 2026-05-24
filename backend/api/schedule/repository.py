"""Repository layer for schedule data."""
from __future__ import annotations

import json
import logging
import time

from api.models import SeasonSchedule
from api.common.request_id import get_request_id
from api.services.cache import build_cache_key, ttl_for, get_from_cache, set_in_cache

logger = logging.getLogger(__name__)


def get_persisted_season_schedule(year: int) -> list[dict] | None:
    """Return the persisted season schedule for a given year via cache-first pattern."""
    cache_key = build_cache_key(year, 0, "schedule", "schedule")
    
    # Step 1: Check Redis cache
    cached_data = get_from_cache(cache_key)
    if cached_data is not None:
        logger.info(
            "event=cache_hit",
            extra={"request_id": get_request_id(), "cache_key": cache_key, "source": "redis"},
        )
        try:
            return json.loads(cached_data) if isinstance(cached_data, str) else cached_data
        except (json.JSONDecodeError, TypeError):
            pass  # Fall through to DB
    
    # Step 2: Check PostgreSQL database
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "SeasonSchedule",
            "year": year,
        },
    )
    start_time = time.time()
    record = SeasonSchedule.objects.filter(year=year).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = record is not None
    rows = len(record.payload.get("races", [])) if record else 0
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "SeasonSchedule",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
            "cache_key": cache_key,
        },
    )
    
    if record is None:
        return None
    
    races_list = record.payload.get("races", [])
    
    # Step 3: Backfill Redis cache
    ttl = ttl_for("schedule", year)
    set_in_cache(cache_key, json.dumps(races_list), ttl)
    logger.info(
        "event=cache_write",
        extra={"request_id": get_request_id(), "cache_key": cache_key, "ttl_seconds": ttl},
    )
    
    return races_list


def get_persisted_race_by_round(year: int, round_number: int) -> dict | None:
    """Return a single race's info from the persisted schedule."""
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "SeasonSchedule",
            "year": year,
            "round": round_number,
        },
    )
    start_time = time.time()
    record = SeasonSchedule.objects.filter(year=year).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = False
    result = None
    if record is not None:
        for race in record.payload.get("races", []):
            if race.get("round") == round_number:
                hit = True
                result = race
                break
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "SeasonSchedule",
            "hit": hit,
            "rows": 1 if hit else 0,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )
    
    return result
