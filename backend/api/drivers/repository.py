"""Repository layer for driver data — all ORM queries live here."""
from __future__ import annotations

import json
import logging
import time

from api.models import DriverStandings, DriverCareer, DriverSeasonBreakdown
from api.common.request_id import get_request_id
from api.services.cache import build_cache_key, ttl_for, get_from_cache, set_in_cache

logger = logging.getLogger(__name__)


def get_persisted_driver_standings(year: int) -> list[dict] | None:
    """Return the persisted driver standings list for a given year via cache-first pattern."""
    cache_key = build_cache_key(year, 0, "standings", "standings")
    
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
            "table": "DriverStandings",
            "year": year,
        },
    )
    start_time = time.time()
    record = DriverStandings.objects.filter(year=year).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = record is not None
    rows_data = record.payload.get("standings", []) if record else []
    rows = len(rows_data)
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "DriverStandings",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
            "cache_key": cache_key,
        },
    )
    
    if not rows_data:
        return None
    
    # Step 3: Backfill Redis cache
    ttl = ttl_for("standings", year)
    set_in_cache(cache_key, json.dumps(rows_data), ttl)
    logger.info(
        "event=cache_write",
        extra={"request_id": get_request_id(), "cache_key": cache_key, "ttl_seconds": ttl},
    )
    
    return rows_data


def get_persisted_driver_career(driver_code: str) -> dict | None:
    """
    Return the persisted DriverCareer payload for a driver via cache-first pattern.
    Returns the full payload dict: {driver_name, nationality, career, career_totals}.
    """
    # Note: driver_code is used in cache key instead of round_number
    cache_key = f"f1:career:{driver_code.upper()}"
    
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
            "table": "DriverCareer",
            "driver_code": driver_code,
        },
    )
    start_time = time.time()
    normalized_code = str(driver_code).upper()
    record = DriverCareer.objects.filter(driver_code=normalized_code).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = record is not None
    rows = 1 if record else 0
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "DriverCareer",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
            "cache_key": cache_key,
        },
    )
    
    if record is None:
        return None
    
    payload = dict(record.payload or {})
    
    # Step 3: Backfill Redis cache
    ttl = ttl_for("career", 2020)  # Career data is historical (7 days per cache.py logic)
    set_in_cache(cache_key, json.dumps(payload), ttl)
    logger.info(
        "event=cache_write",
        extra={"request_id": get_request_id(), "cache_key": cache_key, "ttl_seconds": ttl},
    )
    
    return payload


def get_persisted_driver_season_breakdown(driver_code: str, year: int) -> dict | None:
    """
    Return the persisted DriverSeasonBreakdown payload for (driver_code, year), or None.
    Returns the full payload dict: {driver_name, constructor, final_position, final_points, races}.
    """
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "DriverSeasonBreakdown",
            "driver_code": driver_code,
            "year": year,
        },
    )
    start_time = time.time()
    normalized_code = str(driver_code).upper()
    record = DriverSeasonBreakdown.objects.filter(
        driver_code=normalized_code, year=int(year)
    ).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = record is not None
    rows = 1 if record else 0
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "DriverSeasonBreakdown",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )
    
    if record is None:
        return None
    return dict(record.payload or {})
