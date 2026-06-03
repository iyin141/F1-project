from __future__ import annotations

from typing import Optional

from api.models import (
    ConstructorStandings,
    DriverCareer,
    DriverLapAnalysis,
    DriverSeasonBreakdown,
    DriverStandings,
    DriverTelemetry,
    PracticeResultData,
    QualifyingResultData,
    RaceResultData,
    SeasonSchedule,
)


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


def get_persisted_lap_analysis(
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
        laps = db_row.payload.get("laps", [])
        if driver:
            # If we filtered by driver in the query, we just take them
            rows.extend(laps)
        else:
            # If we didn't filter by driver, we need to add driver_code to each lap
            for lap in laps:
                rows.append({**lap, "driver_code": db_row.driver_code})

    if limit is not None:
        rows = rows[:limit]

    # Backwards-compatibility: ensure required serializer fields exist
    for r in rows:
        # ensure laps_in_stint present as integer (prefer total_laps)
        if "laps_in_stint" not in r:
            if isinstance(r.get("total_laps"), int):
                r["laps_in_stint"] = r.get("total_laps")
            else:
                lap_start = r.get("lap_start")
                lap_end = r.get("lap_end")
                if isinstance(lap_start, int) and isinstance(lap_end, int):
                    try:
                        r["laps_in_stint"] = max(0, int(lap_end) - int(lap_start) + 1)
                    except Exception:
                        r["laps_in_stint"] = 0
                else:
                    r["laps_in_stint"] = 0

        # Ensure optional numeric fields exist to avoid serializer KeyError
        r.setdefault("avg_lap_seconds", None)
        r.setdefault("degradation_seconds", None)

    readiness = _build_readiness(True, ["laps"], [], None)
    if not rows:
        message = f"No persisted lap analysis data found for {year} Round {round_number}."
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

# ---------------------------------------------------------------------------
# Qualifying / sprint / practice
# ---------------------------------------------------------------------------

def get_persisted_qualifying_results(year, round_number):
    from api.services.extraction import extract_qualifying_results
    record = QualifyingResultData.objects.filter(year=year, round_number=round_number).first()
    if record is None:
        return None
    rows = extract_qualifying_results(record.payload)
    return rows if rows else None


def get_persisted_sprint_results(year, round_number):
    from api.services.extraction import extract_sprint_results
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="S").first()
    if record is None:
        return None
    rows = extract_sprint_results(record.payload)
    return rows if rows else None


def get_persisted_sprint_shootout_results(year, round_number):
    from api.services.extraction import extract_sprint_shootout_results
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="SQ").first()
    if record is None:
        return None
    rows = extract_sprint_shootout_results(record.payload)
    return rows if rows else None


def get_persisted_practice_results(year, round_number, session):
    from api.services.extraction import extract_practice_results
    normalized = _normalize_session(session)
    record = PracticeResultData.objects.filter(year=year, round_number=round_number, session=normalized).first()
    if record is None:
        return None
    rows = extract_practice_results(record.payload)
    return rows if rows else None


# ---------------------------------------------------------------------------
# Driver standings
# ---------------------------------------------------------------------------

def get_persisted_driver_standings(year):
    from api.services.extraction import extract_driver_standings
    record = DriverStandings.objects.filter(year=year, driver_code__isnull=True).first()
    if record is None:
        return None
    rows = extract_driver_standings(record.payload)
    return rows if rows else None


def get_persisted_constructor_standings(year):
    """Return the persisted constructor standings list for a given year, or None."""
    record = ConstructorStandings.objects.filter(year=year).first()
    if record is None:
        return None
    rows = record.payload.get("standings", [])
    return rows if rows else None


def get_persisted_driver_career(driver_code: str):
    """
    Return the persisted DriverCareer payload for a driver, or None.
    Returns the full payload dict: {driver_name, nationality, career, career_totals}.
    """
    normalized_code = str(driver_code).upper()
    record = DriverCareer.objects.filter(driver_code=normalized_code).first()
    if record is None:
        return None
    return dict(record.payload or {})


def get_persisted_driver_season_breakdown(driver_code: str, year: int):
    """
    Return the persisted DriverSeasonBreakdown payload for (driver_code, year), or None.
    Returns the full payload dict: {driver_name, constructor, final_position, final_points, races}.
    """
    normalized_code = str(driver_code).upper()
    record = DriverSeasonBreakdown.objects.filter(
        driver_code=normalized_code, year=int(year)
    ).first()
    if record is None:
        return None
    return dict(record.payload or {})


# ---------------------------------------------------------------------------
# Session-wide / unified data
# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def get_persisted_driver_telemetry(
    year,
    round_number,
    session,
    driver_code: str,
) -> Optional[dict]:
    """
    Return the full laps payload for one driver in a session, or None.
    Payload shape: {"1": {field: [values]}, "2": {...}, ...}
    """
    normalized_session = _normalize_session(session)
    normalized_driver = str(driver_code).upper()
    record = DriverTelemetry.objects.filter(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver_code=normalized_driver,
    ).first()
    if record is None:
        return None
    return dict(record.payload or {})


def get_persisted_lap_telemetry(
    year,
    round_number,
    session,
    driver_code: str,
    lap: int,
) -> Optional[dict]:
    """
    Return telemetry for one specific lap, sliced from the driver's payload in Python.
    Returns None if the driver row doesn’t exist or the lap key is absent.
    """
    full = get_persisted_driver_telemetry(year, round_number, session, driver_code)
    if full is None:
        return None
    return full.get(str(lap))
