from __future__ import annotations

from typing import Optional

from api.models import DriverLapAnalysis, RaceResultData, SeasonSchedule

_MAX_LIMIT = 2000


def _build_readiness(can_proceed: bool, available_data: list[str], unavailable_data: list[str], message: str | None = None):
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": [] if can_proceed else ([message] if message else []),
    }


def _normalize_session(session: str) -> str:
    return str(session).upper()


def get_persisted_race_by_round(year: int, round_number: int) -> Optional[dict]:
    record = SeasonSchedule.objects.filter(year=year).first()
    if record is None:
        return None
    for race in record.payload.get("races", []):
        if race.get("round") == round_number:
            return race
    return None


def get_persisted_season_schedule(year: int) -> list[dict]:
    record = SeasonSchedule.objects.filter(year=year).first()
    if record is None:
        return []
    return list(record.payload.get("races", []))


def get_persisted_race_results(year: int, round_number: int) -> Optional[list[dict]]:
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    if record is None:
        return None
    results = record.payload.get("results", [])
    if not results:
        return None
    return results


def _get_driver_lap_rows(year: int, round_number: int, session: str, driver: Optional[str]) -> list:
    """Return DriverLapAnalysis rows for (year, round, session), optionally filtered by driver."""
    qs = DriverLapAnalysis.objects.filter(
        year=year,
        round_number=round_number,
        session=_normalize_session(session),
    )
    if driver:
        qs = qs.filter(driver_code=driver.upper())
    return list(qs)


def get_persisted_stint_analysis(
    year: int,
    round_number: int,
    session: str,
    driver: Optional[str],
    limit: Optional[int],
):
    if _normalize_session(session) != "R":
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    db_rows = _get_driver_lap_rows(year, round_number, session, normalized_driver)

    rows: list[dict] = []
    for db_row in db_rows:
        rows.extend(db_row.payload.get("stints", []))

    if limit is not None:
        rows = rows[:limit]

    readiness = _build_readiness(True, ["laps"], [], None)
    if not rows:
        message = f"No persisted stint analysis data found for {year} Round {round_number}."
        readiness = _build_readiness(False, [], ["laps"], message)

    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": "R",
            "row_count": len(rows),
            "limit_max": _MAX_LIMIT,
            "readiness": readiness,
        },
        "filters_applied": {
            "driver": normalized_driver,
            "limit": limit,
        },
        "data": rows,
    }


def get_persisted_pace_analysis(
    year: int,
    round_number: int,
    session: str,
    driver: Optional[str],
    limit: Optional[int],
):
    if _normalize_session(session) != "R":
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    db_rows = _get_driver_lap_rows(year, round_number, session, normalized_driver)

    rows: list[dict] = []
    for db_row in db_rows:
        pace = db_row.payload.get("pace")
        if pace:
            rows.append({**pace, "driver_code": db_row.driver_code})

    # Sort by session_median_lap_seconds ascending (fastest first), nulls last
    rows.sort(key=lambda r: (r.get("session_median_lap_seconds") is None, r.get("session_median_lap_seconds")))

    if limit is not None:
        rows = rows[:limit]

    readiness = _build_readiness(True, ["laps"], [], None)
    if not rows:
        message = f"No persisted pace analysis data found for {year} Round {round_number}."
        readiness = _build_readiness(False, [], ["laps"], message)

    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": "R",
            "row_count": len(rows),
            "limit_max": _MAX_LIMIT,
            "readiness": readiness,
        },
        "filters_applied": {
            "driver": normalized_driver,
            "limit": limit,
        },
        "data": rows,
    }


def get_persisted_tyre_strategy_analysis(
    year: int,
    round_number: int,
    session: str,
    driver: Optional[str],
    limit: Optional[int],
):
    if _normalize_session(session) != "R":
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    db_rows = _get_driver_lap_rows(year, round_number, session, normalized_driver)

    rows: list[dict] = []
    for db_row in db_rows:
        rows.extend(db_row.payload.get("tyre_strategy", []))

    if limit is not None:
        rows = rows[:limit]

    readiness = _build_readiness(True, ["laps"], [], None)
    if not rows:
        message = f"No persisted tyre strategy data found for {year} Round {round_number}."
        readiness = _build_readiness(False, [], ["laps"], message)

    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": "R",
            "row_count": len(rows),
            "limit_max": _MAX_LIMIT,
            "readiness": readiness,
        },
        "filters_applied": {
            "driver": normalized_driver,
            "limit": limit,
        },
        "data": rows,
    }


def get_persisted_sector_analysis(
    year: int,
    round_number: int,
    session: str,
    driver: Optional[str],
    limit: Optional[int],
):
    if _normalize_session(session) != "R":
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    db_rows = _get_driver_lap_rows(year, round_number, session, normalized_driver)

    rows: list[dict] = []
    for db_row in db_rows:
        sectors = db_row.payload.get("sectors")
        if sectors:
            rows.append({**sectors, "driver_code": db_row.driver_code})

    # Sort by theoretical_best_lap_seconds ascending, nulls last
    rows.sort(key=lambda r: (r.get("theoretical_best_lap_seconds") is None, r.get("theoretical_best_lap_seconds")))

    if limit is not None:
        rows = rows[:limit]

    readiness = _build_readiness(True, ["laps"], [], None)
    if not rows:
        message = f"No persisted sector analysis data found for {year} Round {round_number}."
        readiness = _build_readiness(False, [], ["laps"], message)

    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": "R",
            "row_count": len(rows),
            "limit_max": _MAX_LIMIT,
            "readiness": readiness,
        },
        "filters_applied": {
            "driver": normalized_driver,
            "limit": limit,
        },
        "data": rows,
    }
