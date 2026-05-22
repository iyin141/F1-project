"""Repository layer for results data."""
from __future__ import annotations

import logging
import time

from api.models import RaceResultData, QualifyingResultData, PracticeResultData
from api.common.request_id import get_request_id

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

    if record is None:
        return None
    return rows_list


def get_persisted_qualifying_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted qualifying results."""
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
        },
    )

    if record is None:
        return None
    return rows_list


def get_persisted_race_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted race results."""
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
        },
    )

    if record is None:
        return None
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
