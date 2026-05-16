"""Heavy analysis service helpers for opt-in lap-level endpoints."""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from .fastf1_runtime import fastf1
from .persistence import (
    get_persisted_pace_analysis,
    get_persisted_sector_analysis,
    get_persisted_stint_analysis,
    get_persisted_lap_analysis,
    get_persisted_driver_telemetry,
    get_persisted_lap_telemetry,
    get_persisted_tyre_strategy_analysis,
)
from .readiness import build_readiness, classify_fastf1_exception
from .utils import is_current_year, is_round_completed
from api.tasks import populate_telemetry, populate_race_results
from api.services.task_manager import TaskManager


logger = logging.getLogger(__name__)

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
_MAX_LIMIT = 2000
_MAX_TELEMETRY_POINTS = 3000
_DEFAULT_TELEMETRY_POINTS = 800
_TELEMETRY_MIN_YEAR = 2018  # FastF1 telemetry not available before 2018
def _dataset_available(session, attr_name: str) -> bool:
    """Check whether a loaded session dataset exists and has rows."""
    try:
        dataset = getattr(session, attr_name)
    except Exception:
        return False

    if dataset is None:
        return False

    if hasattr(dataset, "empty"):
        try:
            return not bool(dataset.empty)
        except Exception:
            return False

    return True


def _laps_available(session) -> bool:
    if not _dataset_available(session, "laps"):
        return False
    laps = session.laps
    if "LapTime" not in laps.columns:
        return False
    return bool(laps["LapTime"].notna().any())


def _readiness_payload(
    *,
    can_proceed: bool,
    available_data: list[str],
    unavailable_data: list[str],
    message: str | None,
    warnings: list[str] | None = None,
) -> dict:
    return build_readiness(can_proceed, available_data, unavailable_data, message, warnings)


def _load_session_with_readiness(
    *,
    year: int,
    round_number: int,
    session: str,
    telemetry: bool,
    weather: bool,
    messages: bool,
    required_data: tuple[str, ...],
):
    """Load a FastF1 session and return readiness checklist information."""
    try:
        loaded_session = fastf1.get_session(year, round_number, session)
        loaded_session.load(telemetry=telemetry, weather=weather, messages=messages)
    except Exception as exc:
        readiness = classify_fastf1_exception(
            exc,
            year=year,
            round_number=round_number,
            session_name=session,
            required_data=required_data,
        )
        if readiness is not None:
            return None, readiness
        raise

    available = []
    if _laps_available(loaded_session):
        available.append("laps")
    if _dataset_available(loaded_session, "weather"):
        available.append("weather")
    if _dataset_available(loaded_session, "messages"):
        available.append("messages")
    if _dataset_available(loaded_session, "track_status"):
        available.append("track_status")

    unavailable = [item for item in required_data if item not in available]
    can_proceed = len(unavailable) == 0

    message = None
    warnings = []
    if not can_proceed:
        message = (
            f"Session loaded, but required data is unavailable for {year} Round {round_number} ({session}). "
            f"Missing: {', '.join(unavailable)}."
        )
        warnings.append(message)

    return loaded_session, _readiness_payload(
        can_proceed=can_proceed,
        available_data=available,
        unavailable_data=unavailable,
        message=message,
        warnings=warnings,
    )


def _safe_int(value):
    if pd.isna(value):
        return None
    return int(value)


def _safe_time_str(value):
    if pd.isna(value):
        return None
    return str(value)


def _safe_bool(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return bool(value)


def _safe_float(value, precision=3):
    if value is None or pd.isna(value):
        return None
    return round(float(value), precision)


def _lap_seconds(value):
    if value is None or pd.isna(value):
        return None

    if hasattr(value, "total_seconds"):
        return value.total_seconds()

    try:
        return pd.to_timedelta(value).total_seconds()
    except Exception:
        return None


def _validate_sector_window(sector_start: Optional[int], sector_end: Optional[int]):
    if sector_start is None and sector_end is None:
        return

    if sector_start is None or sector_end is None:
        raise ValueError("sector_start and sector_end must be provided together")

    if sector_start < 1 or sector_start > 3 or sector_end < 1 or sector_end > 3:
        raise ValueError("sector_start and sector_end must be between 1 and 3")

    if sector_start > sector_end:
        raise ValueError("sector_start must be less than or equal to sector_end")


def _apply_sector_window(telemetry: pd.DataFrame, sector_start: Optional[int], sector_end: Optional[int]):
    if sector_start is None or sector_end is None:
        return telemetry

    if "Distance" not in telemetry.columns or telemetry.empty:
        return telemetry

    max_distance = telemetry["Distance"].max()
    if pd.isna(max_distance) or max_distance <= 0:
        return telemetry

    sector_size = float(max_distance) / 3.0
    start_distance = (sector_start - 1) * sector_size
    end_distance = sector_end * sector_size
    return telemetry[(telemetry["Distance"] >= start_distance) & (telemetry["Distance"] <= end_distance)]


def _telemetry_rows_from_frame(telemetry: pd.DataFrame):
    telemetry_rows = []
    for _, row in telemetry.iterrows():
        telemetry_rows.append(
            {
                "time_seconds": _safe_float(_lap_seconds(row.get("Time")), precision=4),
                "distance_m": _safe_float(row.get("Distance"), precision=3),
                "speed_kph": _safe_float(row.get("Speed"), precision=2),
                "throttle_pct": _safe_float(row.get("Throttle"), precision=2),
                "brake": _safe_bool(row.get("Brake")),
                "rpm": _safe_int(row.get("RPM")),
                "gear": _safe_int(row.get("nGear")),
            }
        )
    return telemetry_rows


def _extract_driver_lap_telemetry(
    telemetry_session,
    normalized_driver: str,
    lap: Optional[int],
    limit_points: int,
    stride: int,
    sector_start: Optional[int],
    sector_end: Optional[int],
):
    laps = telemetry_session.laps.pick_drivers([normalized_driver])

    selected_lap_number = lap
    if selected_lap_number is None:
        valid_laps = laps[laps["LapTime"].notna()]
        if valid_laps.empty:
            raise ValueError(f"No telemetry data found for driver {normalized_driver}")
        selected_lap_number = int(valid_laps.sort_values(by="LapTime").iloc[0]["LapNumber"])

    lap_rows = laps[laps["LapNumber"] == selected_lap_number]
    if lap_rows.empty:
        raise ValueError(f"No telemetry data found for driver {normalized_driver} lap {selected_lap_number}")

    selected_lap = lap_rows.sort_values(by="LapTime", na_position="last").iloc[0]
    telemetry = selected_lap.get_car_data().add_distance().copy()

    if telemetry.empty:
        raise ValueError(f"No telemetry samples available for driver {normalized_driver} lap {selected_lap_number}")

    telemetry = _apply_sector_window(telemetry, sector_start, sector_end)

    if stride > 1:
        telemetry = telemetry.iloc[::stride]

    if len(telemetry) > limit_points:
        downsample_step = max(1, math.ceil(len(telemetry) / limit_points))
        telemetry = telemetry.iloc[::downsample_step]

    return int(selected_lap_number), telemetry


def get_lap_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return normalized lap-level analysis rows for a race session."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    # Historical Race session: DB-first
    if normalized_session == "R" and is_round_completed(year, round_number):
        persisted = get_persisted_lap_analysis(
            year=year,
            round_number=round_number,
            session=normalized_session,
            driver=normalized_driver,
            limit=limit,
        )
        if persisted is not None and persisted.get("data"):
            logger.info(
                "[LapsView] DB hit year=%s round=%s driver=%s",
                year, round_number, normalized_driver,
            )
            return persisted

    try:
        lap_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=False,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_LIMIT,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "limit": limit,
                },
                "data": [],
            }

        laps = lap_session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if normalized_driver:
            laps = laps[laps["Driver"].astype(str).str.upper() == normalized_driver]

        if limit is not None:
            laps = laps.head(limit)

        analysis_rows = []
        for _, row in laps.iterrows():
            analysis_rows.append(
                {
                    "driver_code": row.get("Driver", "Unknown"),
                    "lap_number": _safe_int(row.get("LapNumber")),
                    "lap_time": _safe_time_str(row.get("LapTime")),
                    "sector1": _safe_time_str(row.get("Sector1Time")),
                    "sector2": _safe_time_str(row.get("Sector2Time")),
                    "sector3": _safe_time_str(row.get("Sector3Time")),
                    "compound": row.get("Compound") if pd.notna(row.get("Compound")) else None,
                    "stint": _safe_int(row.get("Stint")),
                    "is_personal_best": _safe_bool(row.get("IsPersonalBest")),
                }
            )

        if normalized_session == "R" and is_round_completed(year, round_number):
            TaskManager.enqueue_if_needed(
                task_key=f"race_results:{int(year)}:{int(round_number)}",
                task_fn=populate_race_results,
                year=int(year),
                round_number=int(round_number),
                session_type="R",
            )

        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(analysis_rows),
                "limit_max": _MAX_LIMIT,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "limit": limit,
            },
            "data": analysis_rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching lap analysis for {year} Round {round_number}: {str(exc)}")


def get_stint_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return stint-level aggregates for a race session."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted_payload = get_persisted_stint_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted_payload is not None and persisted_payload.get("data"):
        return persisted_payload

    try:
        lap_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=False,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_LIMIT,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "limit": limit,
                },
                "data": [],
            }

        laps = lap_session.laps.copy()
        laps = laps[laps["LapTime"].notna()]
        laps = laps[laps["Stint"].notna()]

        if normalized_driver:
            laps = laps[laps["Driver"].astype(str).str.upper() == normalized_driver]

        if laps.empty:
            stint_rows = []
        else:
            laps["lap_seconds"] = laps["LapTime"].apply(_lap_seconds)

            grouped = (
                laps.groupby(["Driver", "DriverNumber", "Stint"], dropna=True)
                .agg(
                    compound=("Compound", lambda s: s.dropna().iloc[-1] if not s.dropna().empty else None),
                    lap_start=("LapNumber", "min"),
                    lap_end=("LapNumber", "max"),
                    total_laps=("LapNumber", "count"),
                    median_lap_seconds=("lap_seconds", "median"),
                    min_lap_seconds=("lap_seconds", "min"),
                    max_lap_seconds=("lap_seconds", "max"),
                )
                .reset_index()
            )

            grouped = grouped.sort_values(by=["Driver", "Stint"], ascending=[True, True])
            if limit is not None:
                grouped = grouped.head(limit)

            stint_rows = []
            for _, row in grouped.iterrows():
                stint_rows.append(
                    {
                        "driver_code": row.get("Driver", "Unknown"),
                        "driver_number": _safe_int(row.get("DriverNumber")),
                        "stint_number": _safe_int(row.get("Stint")),
                        "compound": row.get("compound") if pd.notna(row.get("compound")) else None,
                        "lap_start": _safe_int(row.get("lap_start")),
                        "lap_end": _safe_int(row.get("lap_end")),
                        "total_laps": _safe_int(row.get("total_laps")) or 0,
                        "median_lap_seconds": _safe_float(row.get("median_lap_seconds")),
                        "min_lap_seconds": _safe_float(row.get("min_lap_seconds")),
                        "max_lap_seconds": _safe_float(row.get("max_lap_seconds")),
                    }
                )

        if normalized_session == "R" and is_round_completed(year, round_number):
            TaskManager.enqueue_if_needed(
                task_key=f"race_results:{int(year)}:{int(round_number)}",
                task_fn=populate_race_results,
                year=int(year),
                round_number=int(round_number),
                session_type="R",
            )

        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(stint_rows),
                "limit_max": _MAX_LIMIT,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "limit": limit,
            },
            "data": stint_rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching stint analysis for {year} Round {round_number}: {str(exc)}")


def get_pace_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return driver pace aggregates for a race session."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted_payload = get_persisted_pace_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted_payload is not None and persisted_payload.get("data"):
        return persisted_payload

    try:
        lap_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=False,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_LIMIT,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "limit": limit,
                },
                "data": [],
            }

        laps = lap_session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if normalized_driver:
            laps = laps[laps["Driver"].astype(str).str.upper() == normalized_driver]

        if laps.empty:
            pace_rows = []
        else:
            laps = laps.copy()
            laps["lap_seconds"] = laps["LapTime"].apply(_lap_seconds)

            pace_rows = []
            for (driver_code, driver_number), group in laps.groupby(["Driver", "DriverNumber"], dropna=True):
                group = group.sort_values(by="LapNumber")
                lap_seconds = group["lap_seconds"].dropna()
                lap_count = int(lap_seconds.shape[0])

                improvement = None
                if lap_count >= 6:
                    segment_size = max(1, lap_count // 3)
                    first_segment = lap_seconds.iloc[:segment_size]
                    last_segment = lap_seconds.iloc[-segment_size:]
                    if not first_segment.empty and not last_segment.empty:
                        improvement = first_segment.median() - last_segment.median()

                pace_rows.append(
                    {
                        "driver_code": str(driver_code),
                        "driver_number": _safe_int(driver_number),
                        "laps_completed": lap_count,
                        "session_median_lap_seconds": _safe_float(lap_seconds.median()),
                        "session_best_lap_seconds": _safe_float(lap_seconds.min()),
                        "consistency_stddev_seconds": _safe_float(lap_seconds.std()),
                        "pace_improvement_seconds": _safe_float(improvement),
                    }
                )

            pace_rows = sorted(
                pace_rows,
                key=lambda row: (row["session_median_lap_seconds"] is None, row["session_median_lap_seconds"]),
            )
            if limit is not None:
                pace_rows = pace_rows[:limit]

        if normalized_session == "R" and is_round_completed(year, round_number):
            TaskManager.enqueue_if_needed(
                task_key=f"race_results:{int(year)}:{int(round_number)}",
                task_fn=populate_race_results,
                year=int(year),
                round_number=int(round_number),
                session_type="R",
            )

        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(pace_rows),
                "limit_max": _MAX_LIMIT,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "limit": limit,
            },
            "data": pace_rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching pace analysis for {year} Round {round_number}: {str(exc)}")


def get_telemetry_snapshot(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    lap: Optional[int] = None,
    limit_points: Optional[int] = None,
    stride: int = 1,
    sector_start: Optional[int] = None,
    sector_end: Optional[int] = None,
):
    """Return sampled telemetry points for a specific driver lap."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if not driver:
        raise ValueError("driver is required for telemetry endpoint")

    if lap is None or lap < 1:
        raise ValueError("lap must be a positive integer")

    if stride < 1:
        raise ValueError("stride must be a positive integer")

    _validate_sector_window(sector_start, sector_end)

    if limit_points is None:
        limit_points = _DEFAULT_TELEMETRY_POINTS
    elif limit_points < 1:
        raise ValueError("limit_points must be a positive integer")

    limit_points = min(limit_points, _MAX_TELEMETRY_POINTS)
    normalized_driver = str(driver).upper()

    persisted = get_persisted_lap_telemetry(year, round_number, normalized_session, normalized_driver, lap)
    if persisted is not None:
        from api.services.extraction import extract_telemetry
        points = extract_telemetry(persisted)
        if points:
            if stride > 1:
                points = points[::stride]
            if limit_points:
                points = points[:limit_points]
        summary = None
        readiness = build_readiness(True, ["telemetry_snapshot_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(points) if points else 0,
                "limit_max": _MAX_TELEMETRY_POINTS,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "lap": int(lap),
                "limit_points": int(limit_points),
                "stride": int(stride),
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "data": points if points else [],
        }

    try:
        telemetry_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=True,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_TELEMETRY_POINTS,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "lap": int(lap),
                    "limit_points": int(limit_points),
                    "stride": int(stride),
                    "sector_start": sector_start,
                    "sector_end": sector_end,
                },
                "data": [],
            }

        selected_lap_number, telemetry = _extract_driver_lap_telemetry(
            telemetry_session=telemetry_session,
            normalized_driver=normalized_driver,
            lap=lap,
            limit_points=limit_points,
            stride=stride,
            sector_start=sector_start,
            sector_end=sector_end,
        )

        telemetry_rows = _telemetry_rows_from_frame(telemetry)

        if normalized_session == "R" and is_round_completed(year, round_number) and int(year) >= _TELEMETRY_MIN_YEAR:
            TaskManager.enqueue_if_needed(
                task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver}",
                task_fn=populate_telemetry,
                year=int(year),
                round_number=int(round_number),
                session_type=normalized_session,
                driver_code=normalized_driver,
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(telemetry_rows),
                "limit_max": _MAX_TELEMETRY_POINTS,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "lap": int(selected_lap_number),
                "limit_points": int(limit_points),
                "stride": int(stride),
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "data": telemetry_rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching telemetry snapshot for {year} Round {round_number}: {str(exc)}")


def get_telemetry_overlay(
    year: int,
    round_number: int,
    session: str = "R",
    driver_a: Optional[str] = None,
    driver_b: Optional[str] = None,
    lap_a: Optional[int] = None,
    lap_b: Optional[int] = None,
    limit_points: Optional[int] = None,
    stride: int = 1,
    sector_start: Optional[int] = None,
    sector_end: Optional[int] = None,
):
    """Return two telemetry traces for overlay comparisons."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if not driver_a or not driver_b:
        raise ValueError("driver_a and driver_b are required for telemetry overlay")

    if lap_a is not None and lap_a < 1:
        raise ValueError("lap_a must be a positive integer")

    if lap_b is not None and lap_b < 1:
        raise ValueError("lap_b must be a positive integer")

    if stride < 1:
        raise ValueError("stride must be a positive integer")

    _validate_sector_window(sector_start, sector_end)

    if limit_points is None:
        limit_points = _DEFAULT_TELEMETRY_POINTS
    elif limit_points < 1:
        raise ValueError("limit_points must be a positive integer")

    limit_points = min(limit_points, _MAX_TELEMETRY_POINTS)

    normalized_driver_a = str(driver_a).upper()
    normalized_driver_b = str(driver_b).upper()

    # Pre-2018: telemetry not available
    if int(year) < _TELEMETRY_MIN_YEAR:
        return {
            "meta": {
                "year": int(year), "round": int(round_number),
                "session": normalized_session, "row_count": 0,
                "limit_max": _MAX_TELEMETRY_POINTS,
                "can_proceed": False,
                "message": f"Telemetry not available before {_TELEMETRY_MIN_YEAR}.",
            },
            "filters_applied": {
                "driver_a": normalized_driver_a, "driver_b": normalized_driver_b,
                "lap_a": int(lap_a) if lap_a else None, "lap_b": int(lap_b) if lap_b else None,
                "limit_points": int(limit_points), "stride": int(stride),
                "sector_start": sector_start, "sector_end": sector_end,
            },
            "traces": [],
        }

    # Historical Race session: per-driver DB-first, independent per driver
    if normalized_session == "R" and is_round_completed(year, round_number):
        def _get_db_lap_data(driver, lap_req):
            full = get_persisted_driver_telemetry(year, round_number, normalized_session, driver)
            if full is None:
                return None
            # Use requested lap if provided, else try to find best lap
            if lap_req:
                return full.get(str(lap_req))
            # Fall back to first available lap
            for k in sorted(full.keys(), key=lambda x: int(x)):
                return full[k]
            return None

        db_a = _get_db_lap_data(normalized_driver_a, lap_a)
        db_b = _get_db_lap_data(normalized_driver_b, lap_b)
        if db_a is not None and db_b is not None:
            def _to_trace(lap_data, driver, lap_req):
                distances = lap_data.get("distance", [])
                speeds = lap_data.get("speed", [])
                throttles = lap_data.get("throttle", [])
                brakes = lap_data.get("brake", [])
                gears = lap_data.get("gear", [])
                rpms = lap_data.get("rpm", [])
                n = len(distances)
                points = [
                    {
                        "distance_m": distances[i] if i < len(distances) else None,
                        "speed_kph": speeds[i] if i < len(speeds) else None,
                        "throttle_pct": throttles[i] if i < len(throttles) else None,
                        "brake": brakes[i] if i < len(brakes) else False,
                        "gear": gears[i] if i < len(gears) else None,
                        "rpm": rpms[i] if i < len(rpms) else None,
                    }
                    for i in range(n)
                ]
                if stride > 1:
                    points = points[::stride]
                if limit_points:
                    points = points[:limit_points]
                return {"driver": driver, "lap": lap_req, "data": points}

            traces = [_to_trace(db_a, normalized_driver_a, lap_a), _to_trace(db_b, normalized_driver_b, lap_b)]
            logger.info(
                "[OverlayView] DB hit year=%s round=%s driver_a=%s driver_b=%s",
                year, round_number, normalized_driver_a, normalized_driver_b,
            )
            readiness = build_readiness(True, ["telemetry_overlay_persisted"], [], None)
            return {
                "meta": {
                    "year": int(year), "round": int(round_number),
                    "session": normalized_session,
                    "row_count": sum(len(t["data"]) for t in traces),
                    "limit_max": _MAX_TELEMETRY_POINTS, **readiness,
                },
                "filters_applied": {
                    "driver_a": normalized_driver_a, "driver_b": normalized_driver_b,
                    "lap_a": int(lap_a) if lap_a else None, "lap_b": int(lap_b) if lap_b else None,
                    "limit_points": int(limit_points), "stride": int(stride),
                    "sector_start": sector_start, "sector_end": sector_end,
                },
                "traces": traces,
            }

    try:
        telemetry_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=True,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_TELEMETRY_POINTS,
                    **readiness,
                },
                "filters_applied": {
                    "driver_a": normalized_driver_a,
                    "driver_b": normalized_driver_b,
                    "lap_a": int(lap_a) if lap_a is not None else None,
                    "lap_b": int(lap_b) if lap_b is not None else None,
                    "limit_points": int(limit_points),
                    "stride": int(stride),
                    "sector_start": sector_start,
                    "sector_end": sector_end,
                },
                "traces": [],
            }

        selected_lap_a, telemetry_a = _extract_driver_lap_telemetry(
            telemetry_session=telemetry_session,
            normalized_driver=normalized_driver_a,
            lap=lap_a,
            limit_points=limit_points,
            stride=stride,
            sector_start=sector_start,
            sector_end=sector_end,
        )
        selected_lap_b, telemetry_b = _extract_driver_lap_telemetry(
            telemetry_session=telemetry_session,
            normalized_driver=normalized_driver_b,
            lap=lap_b,
            limit_points=limit_points,
            stride=stride,
            sector_start=sector_start,
            sector_end=sector_end,
        )

        traces = [
            {
                "driver": normalized_driver_a,
                "lap": selected_lap_a,
                "data": _telemetry_rows_from_frame(telemetry_a),
            },
            {
                "driver": normalized_driver_b,
                "lap": selected_lap_b,
                "data": _telemetry_rows_from_frame(telemetry_b),
            },
        ]

        row_count = sum(len(trace["data"]) for trace in traces)
        # Enqueue per-driver independently — VER and LEC tasks never block each other
        if normalized_session == "R" and is_round_completed(year, round_number) and int(year) >= _TELEMETRY_MIN_YEAR:
            TaskManager.enqueue_if_needed(
                task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver_a}",
                task_fn=populate_telemetry,
                year=int(year),
                round_number=int(round_number),
                session_type=normalized_session,
                driver_code=normalized_driver_a,
            )
            TaskManager.enqueue_if_needed(
                task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver_b}",
                task_fn=populate_telemetry,
                year=int(year),
                round_number=int(round_number),
                session_type=normalized_session,
                driver_code=normalized_driver_b,
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": row_count,
                "limit_max": _MAX_TELEMETRY_POINTS,
                **readiness,
            },
            "filters_applied": {
                "driver_a": normalized_driver_a,
                "driver_b": normalized_driver_b,
                "lap_a": selected_lap_a,
                "lap_b": selected_lap_b,
                "limit_points": int(limit_points),
                "stride": int(stride),
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "traces": traces,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching telemetry overlay for {year} Round {round_number}: {str(exc)}")


def get_telemetry_summary(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    lap: Optional[int] = None,
    stride: int = 1,
    sector_start: Optional[int] = None,
    sector_end: Optional[int] = None,
):
    """Return compact telemetry summary metrics for fast UI cards."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if not driver:
        raise ValueError("driver is required for telemetry summary endpoint")

    if lap is None or lap < 1:
        raise ValueError("lap must be a positive integer")

    if stride < 1:
        raise ValueError("stride must be a positive integer")

    _validate_sector_window(sector_start, sector_end)

    normalized_driver = str(driver).upper()

    # Pre-2018: telemetry not available
    if int(year) < _TELEMETRY_MIN_YEAR:
        return {
            "meta": {
                "year": int(year), "round": int(round_number),
                "session": normalized_session, "row_count": 0,
                "can_proceed": False,
                "message": f"Telemetry not available before {_TELEMETRY_MIN_YEAR}.",
            },
            "filters_applied": {
                "driver": normalized_driver, "lap": int(lap),
                "stride": int(stride), "sector_start": sector_start, "sector_end": sector_end,
            },
            "summary": {"max_speed_kph": None, "braking_zones": 0, "throttle_on_percentage": None, "samples": 0},
        }

    # Historical Race session: DB-first
    if normalized_session == "R" and is_round_completed(year, round_number):
        lap_data = get_persisted_lap_telemetry(year, round_number, normalized_session, normalized_driver, lap)
        if lap_data is not None:
            speeds = lap_data.get("speed", [])
            brakes = lap_data.get("brake", [])
            throttles = lap_data.get("throttle", [])
            max_speed = round(max(speeds), 2) if speeds else None
            brake_edges = sum(
                1 for i in range(1, len(brakes)) if brakes[i] and not brakes[i - 1]
            )
            throttle_on_pct = round(
                sum(1 for t in throttles if t >= 90) / len(throttles) * 100.0, 2
            ) if throttles else None
            logger.info(
                "[SummaryView] DB hit year=%s round=%s driver=%s lap=%s",
                year, round_number, normalized_driver, lap,
            )
            readiness = build_readiness(True, ["telemetry_summary_persisted"], [], None)
            return {
                "meta": {
                    "year": int(year), "round": int(round_number),
                    "session": normalized_session, "row_count": len(speeds), **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver, "lap": int(lap),
                    "stride": int(stride), "sector_start": sector_start, "sector_end": sector_end,
                },
                "summary": {
                    "max_speed_kph": max_speed,
                    "braking_zones": brake_edges,
                    "throttle_on_percentage": throttle_on_pct,
                    "samples": len(speeds),
                },
            }

    try:
        telemetry_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=True,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_TELEMETRY_POINTS,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "lap": int(lap),
                    "stride": int(stride),
                    "sector_start": sector_start,
                    "sector_end": sector_end,
                },
                "summary": {
                    "max_speed_kph": None,
                    "braking_zones": 0,
                    "throttle_on_percentage": None,
                    "samples": 0,
                },
            }

        selected_lap_number, telemetry = _extract_driver_lap_telemetry(
            telemetry_session=telemetry_session,
            normalized_driver=normalized_driver,
            lap=lap,
            limit_points=_MAX_TELEMETRY_POINTS,
            stride=stride,
            sector_start=sector_start,
            sector_end=sector_end,
        )

        speed_series = telemetry.get("Speed", pd.Series(dtype=float)).dropna()
        brake_series = telemetry.get("Brake", pd.Series(dtype=bool)).fillna(False).astype(bool)
        throttle_series = telemetry.get("Throttle", pd.Series(dtype=float)).dropna()

        max_speed_kph = _safe_float(speed_series.max(), precision=2) if not speed_series.empty else None

        brake_edges = brake_series & ~brake_series.shift(1, fill_value=False)
        braking_zones = int(brake_edges.sum())

        throttle_on_pct = None
        if not throttle_series.empty:
            throttle_on_pct = _safe_float((throttle_series >= 90).mean() * 100.0, precision=2)

        summary = {
            "max_speed_kph": max_speed_kph,
            "braking_zones": braking_zones,
            "throttle_on_percentage": throttle_on_pct,
            "samples": int(len(telemetry)),
        }

        if normalized_session == "R" and is_round_completed(year, round_number) and int(year) >= _TELEMETRY_MIN_YEAR:
            TaskManager.enqueue_if_needed(
                task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver}",
                task_fn=populate_telemetry,
                year=int(year),
                round_number=int(round_number),
                session_type=normalized_session,
                driver_code=normalized_driver,
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": int(len(telemetry)),
                "limit_max": _MAX_TELEMETRY_POINTS,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "lap": int(selected_lap_number),
                "stride": int(stride),
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "summary": summary,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching telemetry summary for {year} Round {round_number}: {str(exc)}")


def get_tyre_strategy_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return stint-by-stint tyre strategy metrics for each driver."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted_payload = get_persisted_tyre_strategy_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted_payload is not None and persisted_payload.get("data"):
        return persisted_payload

    try:
        strategy_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=False,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_LIMIT,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "limit": limit,
                },
                "data": [],
            }

        laps = strategy_session.laps.copy()
        laps = laps[laps["LapTime"].notna()]
        laps = laps[laps["Stint"].notna()]

        if normalized_driver:
            laps = laps[laps["Driver"].astype(str).str.upper() == normalized_driver]

        rows = []
        if not laps.empty:
            laps["lap_seconds"] = laps["LapTime"].apply(_lap_seconds)

            for (driver_code, driver_number, stint_number), group in laps.groupby(
                ["Driver", "DriverNumber", "Stint"], dropna=True
            ):
                group = group.sort_values(by="LapNumber")
                lap_seconds = group["lap_seconds"].dropna()
                lap_count = int(lap_seconds.shape[0])

                degradation = None
                if lap_count >= 4:
                    split = max(1, lap_count // 2)
                    start_segment = lap_seconds.iloc[:split]
                    end_segment = lap_seconds.iloc[-split:]
                    if not start_segment.empty and not end_segment.empty:
                        degradation = end_segment.median() - start_segment.median()

                compound_values = group["Compound"].dropna()
                compound = compound_values.iloc[-1] if not compound_values.empty else None

                rows.append(
                    {
                        "driver_code": str(driver_code),
                        "driver_number": _safe_int(driver_number),
                        "stint_number": _safe_int(stint_number),
                        "compound": compound,
                        "lap_start": _safe_int(group["LapNumber"].min()),
                        "lap_end": _safe_int(group["LapNumber"].max()),
                        "laps_in_stint": lap_count,
                        "avg_lap_seconds": _safe_float(lap_seconds.mean()),
                        "median_lap_seconds": _safe_float(lap_seconds.median()),
                        "degradation_seconds": _safe_float(degradation),
                    }
                )

            rows = sorted(rows, key=lambda item: (item["driver_code"], item["stint_number"]))
            if limit is not None:
                rows = rows[:limit]

        if normalized_session == "R" and is_round_completed(year, round_number):
            TaskManager.enqueue_if_needed(
                task_key=f"race_results:{int(year)}:{int(round_number)}",
                task_fn=populate_race_results,
                year=int(year),
                round_number=int(round_number),
                session_type="R",
            )

        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(rows),
                "limit_max": _MAX_LIMIT,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "limit": limit,
            },
            "data": rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching tyre strategy analysis for {year} Round {round_number}: {str(exc)}")


def get_sector_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return sector-level pace metrics for each driver."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted_payload = get_persisted_sector_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted_payload is not None and persisted_payload.get("data"):
        return persisted_payload

    try:
        sector_session, readiness = _load_session_with_readiness(
            year=year,
            round_number=round_number,
            session=normalized_session,
            telemetry=False,
            weather=False,
            messages=False,
            required_data=("laps",),
        )

        if not readiness["can_proceed"]:
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "limit_max": _MAX_LIMIT,
                    **readiness,
                },
                "filters_applied": {
                    "driver": normalized_driver,
                    "limit": limit,
                },
                "data": [],
            }

        laps = sector_session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if normalized_driver:
            laps = laps[laps["Driver"].astype(str).str.upper() == normalized_driver]

        rows = []
        if not laps.empty:
            laps = laps.copy()
            laps["lap_seconds"] = laps["LapTime"].apply(_lap_seconds)
            laps["s1_seconds"] = laps["Sector1Time"].apply(_lap_seconds)
            laps["s2_seconds"] = laps["Sector2Time"].apply(_lap_seconds)
            laps["s3_seconds"] = laps["Sector3Time"].apply(_lap_seconds)

            for (driver_code, driver_number), group in laps.groupby(["Driver", "DriverNumber"], dropna=True):
                lap_seconds = group["lap_seconds"].dropna()
                s1 = group["s1_seconds"].dropna()
                s2 = group["s2_seconds"].dropna()
                s3 = group["s3_seconds"].dropna()

                best_s1 = _safe_float(s1.min()) if not s1.empty else None
                best_s2 = _safe_float(s2.min()) if not s2.empty else None
                best_s3 = _safe_float(s3.min()) if not s3.empty else None

                theoretical_best = None
                if best_s1 is not None and best_s2 is not None and best_s3 is not None:
                    theoretical_best = _safe_float(best_s1 + best_s2 + best_s3)

                best_lap = _safe_float(lap_seconds.min()) if not lap_seconds.empty else None
                delta_to_theoretical = None
                if best_lap is not None and theoretical_best is not None:
                    delta_to_theoretical = _safe_float(best_lap - theoretical_best)

                rows.append(
                    {
                        "driver_code": str(driver_code),
                        "driver_number": _safe_int(driver_number),
                        "laps_count": int(lap_seconds.shape[0]),
                        "best_sector1_seconds": best_s1,
                        "best_sector2_seconds": best_s2,
                        "best_sector3_seconds": best_s3,
                        "median_sector1_seconds": _safe_float(s1.median()) if not s1.empty else None,
                        "median_sector2_seconds": _safe_float(s2.median()) if not s2.empty else None,
                        "median_sector3_seconds": _safe_float(s3.median()) if not s3.empty else None,
                        "best_lap_seconds": best_lap,
                        "theoretical_best_lap_seconds": theoretical_best,
                        "delta_to_theoretical_seconds": delta_to_theoretical,
                    }
                )

            rows = sorted(
                rows,
                key=lambda item: (
                    item["theoretical_best_lap_seconds"] is None,
                    item["theoretical_best_lap_seconds"],
                ),
            )
            if limit is not None:
                rows = rows[:limit]

        if normalized_session == "R" and is_round_completed(year, round_number):
            TaskManager.enqueue_if_needed(
                task_key=f"race_results:{int(year)}:{int(round_number)}",
                task_fn=populate_race_results,
                year=int(year),
                round_number=int(round_number),
                session_type="R",
            )

        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(rows),
                "limit_max": _MAX_LIMIT,
                **readiness,
            },
            "filters_applied": {
                "driver": normalized_driver,
                "limit": limit,
            },
            "data": rows,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise Exception(f"Error fetching sector analysis for {year} Round {round_number}: {str(exc)}")
