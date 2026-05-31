"""Repository layer for results data."""
from __future__ import annotations

import json
import logging
import time

from api.models import RaceResultData, QualifyingResultData, PracticeResultData
from api.common.request_id import get_request_id
from api.services.cache import build_cache_key, ttl_for, get_from_cache, set_in_cache

logger = logging.getLogger(__name__)


def get_persisted_practice_results(year: int, round_number: int, session: str) -> list[dict] | None:
    """Return the persisted practice results for a given year, round, and session."""
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "PracticeResultData",
            "year": year,
            "round": round_number,
            "session": session,
        },
    )
    start_time = time.time()
    record = PracticeResultData.objects.only("payload").filter(year=year, round_number=round_number, session=session).first()
    duration_ms = (time.time() - start_time) * 1000

    hit = record is not None
    payload = record.payload or {} if record else {}
    rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
    rows = len(rows_list) if record else 0

    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "PracticeResultData",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )

    # Inspect payload shape to help diagnose worker persistence parity issues
    try:
        has_data_key = payload.get("data") is not None
        sample_keys = list(rows_list[0].keys()) if rows_list else []
    except Exception:
        has_data_key = False
        sample_keys = []

    logger.info(
        "event=payload_inspect",
        extra={
            "request_id": get_request_id(),
            "table": "PracticeResultData",
            "has_data": has_data_key,
            "sample_keys": sample_keys,
            "rows": rows,
        },
    )

    if record is None:
        return None
    return rows_list


def get_persisted_qualifying_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted qualifying results via cache-first pattern: Redis → DB → backfill Redis."""
    cache_key = build_cache_key(year, round_number, "Q", "qualifying")
    
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
            "table": "QualifyingResultData",
            "year": year,
            "round": round_number,
        },
    )
    start_time = time.time()
    record = QualifyingResultData.objects.only("payload").filter(year=year, round_number=round_number).first()
    duration_ms = (time.time() - start_time) * 1000

    hit = record is not None
    payload = record.payload or {} if record else {}
    rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
    rows = len(rows_list) if record else 0
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "QualifyingResultData",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
            "cache_key": cache_key,
        },
    )

    # Inspect payload shape to help diagnose worker persistence parity issues
    try:
        has_data_key = payload.get("data") is not None
        sample_keys = list(rows_list[0].keys()) if rows_list else []
    except Exception:
        has_data_key = False
        sample_keys = []

    logger.info(
        "event=payload_inspect",
        extra={
            "request_id": get_request_id(),
            "table": "QualifyingResultData",
            "has_data": has_data_key,
            "sample_keys": sample_keys,
            "rows": rows,
            "cache_key": cache_key,
        },
    )

    if record is None:
        return None
    
    # Step 3: Backfill Redis cache
    ttl = ttl_for("qualifying", year)
    set_in_cache(cache_key, json.dumps(rows_list), ttl)
    logger.info(
        "event=cache_write",
        extra={"request_id": get_request_id(), "cache_key": cache_key, "ttl_seconds": ttl},
    )
    
    return rows_list


def get_persisted_race_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted race results via cache-first pattern: Redis → DB → backfill Redis."""
    cache_key = build_cache_key(year, round_number, "R", "results")
    
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
            "table": "RaceResultData",
            "year": year,
            "round": round_number,
            "session": "R",
        },
    )
    start_time = time.time()
    record = RaceResultData.objects.only("payload").filter(year=year, round_number=round_number, session="R").first()
    duration_ms = (time.time() - start_time) * 1000

    hit = record is not None
    payload = record.payload or {} if record else {}
    rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
    rows = len(rows_list) if record else 0

    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
            "cache_key": cache_key,
        },
    )

    # Inspect payload shape to help diagnose worker persistence parity issues
    try:
        has_data_key = payload.get("data") is not None
        sample_keys = list(rows_list[0].keys()) if rows_list else []
    except Exception:
        has_data_key = False
        sample_keys = []

    logger.info(
        "event=payload_inspect",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "has_data": has_data_key,
            "sample_keys": sample_keys,
            "rows": rows,
            "cache_key": cache_key,
        },
    )

    if record is None:
        return None
    
    # Step 3: Backfill Redis cache
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(rows_list), ttl)
    logger.info(
        "event=cache_write",
        extra={"request_id": get_request_id(), "cache_key": cache_key, "ttl_seconds": ttl},
    )
    
    return rows_list


def get_persisted_sprint_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted sprint results."""
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "year": year,
            "round": round_number,
            "session": "S",
        },
    )
    start_time = time.time()
    record = RaceResultData.objects.only("payload").filter(year=year, round_number=round_number, session="S").first()
    duration_ms = (time.time() - start_time) * 1000

    hit = record is not None
    payload = record.payload or {} if record else {}
    rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
    rows = len(rows_list) if record else 0

    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )

    # Inspect payload shape to help diagnose worker persistence parity issues
    try:
        has_data_key = payload.get("data") is not None
        sample_keys = list(rows_list[0].keys()) if rows_list else []
    except Exception:
        has_data_key = False
        sample_keys = []

    logger.info(
        "event=payload_inspect",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "has_data": has_data_key,
            "sample_keys": sample_keys,
            "rows": rows,
        },
    )

    if record is None:
        return None
    return rows_list


def get_persisted_sprint_shootout_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted sprint shootout results."""
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "year": year,
            "round": round_number,
            "session": "SQ",
        },
    )
    start_time = time.time()
    record = RaceResultData.objects.only("payload").filter(year=year, round_number=round_number, session="SQ").first()
    duration_ms = (time.time() - start_time) * 1000

    hit = record is not None
    payload = record.payload or {} if record else {}
    rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
    rows = len(rows_list) if record else 0

    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "RaceResultData",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )

    if record is None:
        return None
    return rows_list
