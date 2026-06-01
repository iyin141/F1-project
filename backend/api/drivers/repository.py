"""Repository layer for driver data — all ORM queries live here."""
from __future__ import annotations

import json
import logging
import time

from api.models import DriverStandings, DriverCareer, DriverSeasonBreakdown
from api.models import F1Driver
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


def resolve_to_jolpica_id(identifier: str, year: int | None = None) -> str | None:
    """Resolve an arbitrary identifier to a Jolpica `driver_id`.

    The identifier may be:
      - a Jolpica driver_id (e.g., 'max_verstappen') -> returned as-is
      - a 3-letter driver code (e.g., 'HAM') -> resolve via `F1Driver.code`
      - a full or partial name (e.g., 'Lewis Hamilton') -> fuzzy-match against persisted drivers

    This function prefers DB-side exact matches and season-scoped hits when `year` is provided.
    Falls back to simple in-process fuzzy matching using `difflib`.
    """
    if not identifier:
        return None

    ident = str(identifier).strip()

    # Do not treat arbitrary long strings as Jolpica ids. Attempt DB lookups
    # (code, driver_id, name) first and only accept a driver_id if it is
    # found in the `F1Driver` table.

    # Try 3-letter code lookup
    try:
        code = ident.upper()
        q = F1Driver.objects
        if year:
            q = q.filter(seasons__contains=[int(year)])
        drv = q.filter(code=code).first()
        if drv:
            return drv.driver_id
    except Exception:
        # swallow DB errors and continue to other heuristics
        logger.debug("resolve_to_jolpica_id: code lookup failed", exc_info=True)

    # Try exact driver_id match (case-insensitive)
    try:
        q = F1Driver.objects
        if year:
            q = q.filter(seasons__contains=[int(year)])
        drv = q.filter(driver_id__iexact=ident).first()
        if drv:
            return drv.driver_id
    except Exception:
        logger.debug("resolve_to_jolpica_id: driver_id lookup failed", exc_info=True)

    # Try full-name exact (split into given/family name)
    name_parts = ident.split()
    try:
        q = F1Driver.objects
        if year:
            q = q.filter(seasons__contains=[int(year)])
        if len(name_parts) >= 2:
            given = name_parts[0]
            family = " ".join(name_parts[1:])
            drv = q.filter(given_name__iexact=given, family_name__iexact=family).first()
            if drv:
                return drv.driver_id
        # Try family_name only
        drv = q.filter(family_name__iexact=ident).first()
        if drv:
            return drv.driver_id
    except Exception:
        logger.debug("resolve_to_jolpica_id: name exact lookup failed", exc_info=True)

    # Broad icontains search for candidates
    try:
        q = F1Driver.objects
        if year:
            q = q.filter(seasons__contains=[int(year)])
        candidates = list(
            q.filter(
                driver_id__icontains=ident
            )
            .order_by("family_name")[:10]
        )
        if not candidates:
            q2 = F1Driver.objects
            if year:
                q2 = q2.filter(seasons__contains=[int(year)])
            candidates = list(
                q2.filter(
                    code__icontains=ident
                )
                .order_by("family_name")[:10]
            )
        if not candidates:
            q3 = F1Driver.objects
            if year:
                q3 = q3.filter(seasons__contains=[int(year)])
            candidates = list(
                q3.filter(
                    given_name__icontains=ident
                )
                .order_by("family_name")[:10]
            )
    except Exception:
        logger.debug("resolve_to_jolpica_id: icontains search failed", exc_info=True)
        candidates = []

    # If we have candidates, pick best via difflib on full_name and driver_id
    if candidates:
        try:
            import difflib

            choices = [f"{c.given_name} {c.family_name}".strip() for c in candidates]
            # include driver_ids as possible matches
            choices += [c.driver_id for c in candidates]
            match = difflib.get_close_matches(ident, choices, n=1, cutoff=0.5)
            if match:
                matched = match[0]
                for c in candidates:
                    full = f"{c.given_name} {c.family_name}".strip()
                    if full == matched or c.driver_id == matched:
                        return c.driver_id
        except Exception:
            logger.debug("resolve_to_jolpica_id: difflib matching failed", exc_info=True)

    return None
