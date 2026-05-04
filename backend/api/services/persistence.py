from __future__ import annotations

from typing import Optional

from api.models import DriverMetric, Race, RaceResult, SectorAggregate, StintData

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


def _get_populated_race(year: int, round_number: int) -> Optional[Race]:
    return (
        Race.objects.filter(
            season=year,
            round_number=round_number,
            status=Race.Status.COMPLETED,
            populated_at__isnull=False,
        )
        .order_by("-populated_at")
        .first()
    )


def get_persisted_race_by_round(year: int, round_number: int) -> Optional[dict]:
    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    return {
        "round": race.round_number,
        "name": race.race_name,
        "date": race.race_date.strftime("%Y-%m-%d") if race.race_date else None,
        "location": race.location,
        "country": race.country,
        "event_format": race.event_format,
        "session1": race.session1,
        "session1_date_utc": race.session1_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session1_date_utc else None,
        "session2": race.session2,
        "session2_date_utc": race.session2_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session2_date_utc else None,
        "session3": race.session3,
        "session3_date_utc": race.session3_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session3_date_utc else None,
        "session4": race.session4,
        "session4_date_utc": race.session4_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session4_date_utc else None,
        "session5": race.session5,
        "session5_date_utc": race.session5_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session5_date_utc else None,
    }


def get_persisted_season_schedule(year: int) -> list[dict]:
    races = Race.objects.filter(
        season=year,
        status=Race.Status.COMPLETED,
        populated_at__isnull=False,
    ).order_by("round_number")

    return [
        {
            "round": race.round_number,
            "name": race.race_name,
            "date": race.race_date.strftime("%Y-%m-%d") if race.race_date else None,
            "location": race.location,
            "country": race.country,
            "event_format": race.event_format,
            "session1": race.session1,
            "session1_date_utc": race.session1_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session1_date_utc else None,
            "session2": race.session2,
            "session2_date_utc": race.session2_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session2_date_utc else None,
            "session3": race.session3,
            "session3_date_utc": race.session3_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session3_date_utc else None,
            "session4": race.session4,
            "session4_date_utc": race.session4_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session4_date_utc else None,
            "session5": race.session5,
            "session5_date_utc": race.session5_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if race.session5_date_utc else None,
        }
        for race in races
    ]


def get_persisted_race_results(year: int, round_number: int) -> Optional[list[dict]]:
    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    result_rows = RaceResult.objects.filter(race=race).order_by("finish_position", "driver_code")
    return [
        {
            "position": row.finish_position,
            "driver_number": row.driver_number,
            "driver_name": row.driver_name,
            "team": row.constructor_name,
            "points": int(row.points) if row.points is not None else 0,
            "status": row.status_text or "Unknown",
            "grid_position": row.grid_position,
            "laps": int(row.laps_completed) if row.laps_completed is not None else 0,
        }
        for row in result_rows
    ]


def get_persisted_stint_analysis(
    year: int,
    round_number: int,
    session: str,
    driver: Optional[str],
    limit: Optional[int],
):
    if _normalize_session(session) != "R":
        return None

    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    queryset = StintData.objects.filter(race=race).order_by("driver_code", "stint_number")
    if normalized_driver:
        queryset = queryset.filter(driver_code=normalized_driver)

    if limit is not None:
        queryset = queryset[:limit]

    rows = [
        {
            "driver_code": row.driver_code,
            "driver_number": row.driver_number,
            "stint_number": row.stint_number,
            "compound": row.compound,
            "lap_start": row.lap_start,
            "lap_end": row.lap_end,
            "total_laps": row.laps_in_stint,
            "median_lap_seconds": float(row.median_lap_seconds) if row.median_lap_seconds is not None else None,
            "min_lap_seconds": float(row.min_lap_seconds) if row.min_lap_seconds is not None else None,
            "max_lap_seconds": float(row.max_lap_seconds) if row.max_lap_seconds is not None else None,
        }
        for row in queryset
    ]

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

    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    metrics_qs = DriverMetric.objects.filter(race=race, season_aggregate=False).order_by("avg_pace_seconds")
    if normalized_driver:
        metrics_qs = metrics_qs.filter(driver_code=normalized_driver)

    if limit is not None:
        metrics_qs = metrics_qs[:limit]

    driver_numbers = {
        rr.driver_code: rr.driver_number
        for rr in RaceResult.objects.filter(race=race).only("driver_code", "driver_number")
    }

    rows = [
        {
            "driver_code": metric.driver_code,
            "driver_number": driver_numbers.get(metric.driver_code),
            "laps_completed": int(metric.valid_lap_count or 0),
            "session_median_lap_seconds": float(metric.avg_pace_seconds) if metric.avg_pace_seconds is not None else None,
            "session_best_lap_seconds": None,
            "consistency_stddev_seconds": float(metric.consistency_score) if metric.consistency_score is not None else None,
            "pace_improvement_seconds": None,
        }
        for metric in metrics_qs
    ]

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

    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    queryset = StintData.objects.filter(race=race).order_by("driver_code", "stint_number")
    if normalized_driver:
        queryset = queryset.filter(driver_code=normalized_driver)

    if limit is not None:
        queryset = queryset[:limit]

    rows = [
        {
            "driver_code": row.driver_code,
            "driver_number": row.driver_number,
            "stint_number": row.stint_number,
            "compound": row.compound,
            "lap_start": row.lap_start,
            "lap_end": row.lap_end,
            "laps_in_stint": row.laps_in_stint,
            "avg_lap_seconds": float(row.avg_lap_seconds) if row.avg_lap_seconds is not None else None,
            "median_lap_seconds": float(row.median_lap_seconds) if row.median_lap_seconds is not None else None,
            "degradation_seconds": float(row.degradation_seconds) if row.degradation_seconds is not None else None,
        }
        for row in queryset
    ]

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

    race = _get_populated_race(year, round_number)
    if race is None:
        return None

    normalized_driver = str(driver).upper() if driver else None
    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    queryset = SectorAggregate.objects.filter(race=race).order_by("theoretical_best_lap_seconds", "driver_code")
    if normalized_driver:
        queryset = queryset.filter(driver_code=normalized_driver)

    if limit is not None:
        queryset = queryset[:limit]

    rows = [
        {
            "driver_code": row.driver_code,
            "driver_number": row.driver_number,
            "laps_count": int(row.laps_count or 0),
            "best_sector1_seconds": float(row.best_sector1_seconds) if row.best_sector1_seconds is not None else None,
            "best_sector2_seconds": float(row.best_sector2_seconds) if row.best_sector2_seconds is not None else None,
            "best_sector3_seconds": float(row.best_sector3_seconds) if row.best_sector3_seconds is not None else None,
            "median_sector1_seconds": float(row.median_sector1_seconds) if row.median_sector1_seconds is not None else None,
            "median_sector2_seconds": float(row.median_sector2_seconds) if row.median_sector2_seconds is not None else None,
            "median_sector3_seconds": float(row.median_sector3_seconds) if row.median_sector3_seconds is not None else None,
            "best_lap_seconds": float(row.best_lap_seconds) if row.best_lap_seconds is not None else None,
            "theoretical_best_lap_seconds": float(row.theoretical_best_lap_seconds)
            if row.theoretical_best_lap_seconds is not None
            else None,
            "delta_to_theoretical_seconds": float(row.delta_to_theoretical_seconds)
            if row.delta_to_theoretical_seconds is not None
            else None,
        }
        for row in queryset
    ]

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
