"""Repository layer for driver data — all ORM queries live here."""
from __future__ import annotations

import logging
import time

from api.models import DriverStandings, DriverCareer, DriverSeasonBreakdown
from api.common.request_id import get_request_id

logger = logging.getLogger(__name__)


def get_persisted_driver_standings(year: int) -> list[dict] | None:
    """Return the persisted driver standings list for a given year, or None."""
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
        },
    )
    
    return rows_data if rows_data else None


def get_persisted_driver_career(driver_code: str) -> dict | None:
    """
    Return the persisted DriverCareer payload for a driver, or None.
    Returns the full payload dict: {driver_name, nationality, career, career_totals}.
    """
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
        },
    )
    
    if record is None:
        return None
    return dict(record.payload or {})


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
