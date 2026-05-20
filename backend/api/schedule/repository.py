"""Repository layer for schedule data."""
from __future__ import annotations

import logging
import time

from api.models import SeasonSchedule
from api.common.request_id import get_request_id

logger = logging.getLogger(__name__)


def get_persisted_season_schedule(year: int) -> list[dict] | None:
    """Return the persisted season schedule for a given year, or None."""
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
        },
    )
    
    if record is None:
        return None
    return record.payload.get("races", [])


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
