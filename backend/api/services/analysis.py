"""Heavy analysis service helpers for opt-in lap-level endpoints."""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import pandas as pd

from .unified_service import SessionManager, resolve_load_params, _FULL_LOAD, fastf1
from .persistence import (
    get_persisted_pace_analysis,
    get_persisted_sector_analysis,
    get_persisted_stint_analysis,
    get_persisted_lap_analysis,
    get_persisted_driver_telemetry,
    get_persisted_lap_telemetry,
    get_persisted_session_telemetry,
    get_persisted_tyre_strategy_analysis,
)
from .readiness import build_readiness, classify_fastf1_exception
from .utils import is_current_year
from django.utils import timezone
from django.utils.timezone import make_aware
from api.tasks import populate_telemetry, populate_session_telemetry, populate_race_results
from api.services.task_manager import TaskManager
# `fastf1` is imported via `unified_service` to allow test shims.


logger = logging.getLogger(__name__)

_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
_MAX_LIMIT = 2000
_MAX_TELEMETRY_POINTS = 1_000_000
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
    # Build minimal required_types list for selective loading via SessionManager
    required_types = []
    if telemetry:
        required_types.append("telemetry")
    if weather:
        required_types.append("weather")
    if messages:
        required_types.append("incidents")  # messages map to incidents
    if "laps" in required_data:
        if "laps" not in required_types:
            required_types.append("laps")
    
    try:
        # Compute minimal load flags for this request and call FastF1 directly
        # so unit tests can patch `fastf1.get_session` at the module level.
        load_params = resolve_load_params(required_types) if required_types else _FULL_LOAD.copy()

        loaded_session = fastf1.get_session(year, round_number, session)
        download_start = time.time()
        try:
            loaded_session.load(**load_params)
        except TypeError:
            # Some test fakes or legacy session implementations don't accept kwargs
            loaded_session.load()
        loaded_session._loaded_flags = load_params.copy()
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
    if _dataset_available(loaded_session, "car_data"):
        available.append("telemetry")

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

    # DB-first check only (FastF1 is handled by background Celery tasks)
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

    return None


def get_stint_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return normalized stint-level analysis rows."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted = get_persisted_stint_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted is not None and persisted.get("data"):
        logger.info(
            "[StintsView] DB hit year=%s round=%s driver=%s",
            year, round_number, normalized_driver,
        )
        return persisted

    return None


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

    persisted = get_persisted_pace_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted is not None and persisted.get("data"):
        logger.info(
            "[PaceView] DB hit year=%s round=%s driver=%s",
            year, round_number, normalized_driver,
        )
        return persisted

    return None


def fetch_telemetry_snapshot(
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
    """Return sampled telemetry points for a specific driver lap (or all drivers / all laps)."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if lap is not None and lap < 1:
        raise ValueError("lap must be a positive integer")

    if stride < 1:
        raise ValueError("stride must be a positive integer")

    _validate_sector_window(sector_start, sector_end)

    if limit_points is None:
        limit_points = _DEFAULT_TELEMETRY_POINTS
    elif limit_points < 1:
        raise ValueError("limit_points must be a positive integer")

    limit_points = min(limit_points, _MAX_TELEMETRY_POINTS)
    
    from api.services.extraction import extract_telemetry
    
    persisted_points = []
    
    if driver:
        normalized_driver = str(driver).upper()
        if lap is not None:
            lap_payload = get_persisted_lap_telemetry(year, round_number, normalized_session, normalized_driver, lap)
            if lap_payload:
                persisted_points = extract_telemetry(lap_payload, lap_number=lap)
                for p in persisted_points:
                    p["driver_code"] = normalized_driver
        else:
            driver_payload = get_persisted_driver_telemetry(year, round_number, normalized_session, normalized_driver)
            if driver_payload:
                for lap_key in sorted(driver_payload.keys(), key=lambda x: int(x)):
                    lap_pts = extract_telemetry(driver_payload[lap_key], lap_number=int(lap_key))
                    for p in lap_pts:
                        p["driver_code"] = normalized_driver
                    persisted_points.extend(lap_pts)
    else:
        session_payload = get_persisted_session_telemetry(year, round_number, normalized_session)
        if session_payload:
            for item in session_payload:
                drv = item["driver_code"]
                drv_payload = item["payload"]
                if lap is not None:
                    lap_payload = drv_payload.get(str(lap))
                    if lap_payload:
                        lap_pts = extract_telemetry(lap_payload, lap_number=lap)
                        for p in lap_pts:
                            p["driver_code"] = drv
                        persisted_points.extend(lap_pts)
                else:
                    for lap_key in sorted(drv_payload.keys(), key=lambda x: int(x)):
                        lap_pts = extract_telemetry(drv_payload[lap_key], lap_number=int(lap_key))
                        for p in lap_pts:
                            p["driver_code"] = drv
                        persisted_points.extend(lap_pts)

    if persisted_points:
        if stride > 1:
            persisted_points = persisted_points[::stride]
        if limit_points and len(persisted_points) > limit_points:
            import math
            step = max(1, math.ceil(len(persisted_points) / limit_points))
            persisted_points = persisted_points[::step]
            
        readiness = build_readiness(True, ["telemetry_snapshot_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(persisted_points),
                "limit_max": _MAX_TELEMETRY_POINTS,
                **readiness,
            },
            "filters_applied": {
                "driver": driver.upper() if driver else None,
                "lap": int(lap) if lap else None,
                "limit_points": int(limit_points),
                "stride": int(stride),
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "data": persisted_points,
        }

    # Enqueue full session cache in background as an optimization
    if int(year) >= _TELEMETRY_MIN_YEAR:
        from api.queue.manager import TaskManager
        from api.workers.tier4_telemetry.populate_session_telemetry import populate_session_telemetry
        TaskManager.enqueue_if_needed(
            task_key=f"telemetry_session_cache:{int(year)}:{int(round_number)}:{normalized_session}",
            task_fn=populate_session_telemetry,
            year=int(year),
            round_number=int(round_number),
            session_type=normalized_session,
        )

    return None


def extract_telemetry_snapshot(
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
    normalized_session = str(session).upper()
    if not driver:
        raise ValueError("driver is required for telemetry endpoint")
    normalized_driver = str(driver).upper()

    telemetry_session, readiness = _load_session_with_readiness(
        year=year,
        round_number=round_number,
        session=normalized_session,
        telemetry=True,
        weather=False,
        messages=False,
        required_data=("telemetry", "laps"),
    )

    if not readiness.get("can_proceed"):
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
                "lap": lap if lap else None,
                "limit_points": limit_points,
                "stride": stride,
                "sector_start": sector_start,
                "sector_end": sector_end,
            },
            "data": [],
        }

    lap_num, points_df = _extract_driver_lap_telemetry(
        telemetry_session,
        normalized_driver,
        lap,
        limit_points or _MAX_TELEMETRY_POINTS,
        stride,
        sector_start,
        sector_end,
    )
    points = _telemetry_rows_from_frame(points_df)

    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": normalized_session,
            "row_count": len(points),
            "limit_max": _MAX_TELEMETRY_POINTS,
            **readiness,
        },
        "filters_applied": {
            "driver": normalized_driver,
            "lap": lap_num,
            "limit_points": limit_points,
            "stride": stride,
            "sector_start": sector_start,
            "sector_end": sector_end,
        },
        "data": points,
    }


def fetch_telemetry_overlay(
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

    def _get_db_lap_data(driver, lap_req):
        full = get_persisted_driver_telemetry(year, round_number, normalized_session, driver)
        if full is None:
            return None
            
        from api.services.extraction import extract_telemetry
        points = []
        if lap_req:
            lap_payload = full.get(str(lap_req))
            if lap_payload:
                points = extract_telemetry(lap_payload, lap_number=lap_req)
        else:
            for lap_key in sorted(full.keys(), key=lambda x: int(x)):
                points.extend(extract_telemetry(full[lap_key], lap_number=int(lap_key)))
        return points if points else None

    db_a_points = _get_db_lap_data(normalized_driver_a, lap_a)
    db_b_points = _get_db_lap_data(normalized_driver_b, lap_b)
    if db_a_points is not None and db_b_points is not None:
        def _to_trace(points, driver, lap_req):
            if stride > 1:
                points = points[::stride]
            if limit_points and len(points) > limit_points:
                import math
                step = max(1, math.ceil(len(points) / limit_points))
                points = points[::step]
            return {"driver": driver, "lap": lap_req, "data": points}

        traces = [_to_trace(db_a_points, normalized_driver_a, lap_a), _to_trace(db_b_points, normalized_driver_b, lap_b)]
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

    # Enqueue full session cache in background as an optimization
    if int(year) >= _TELEMETRY_MIN_YEAR:
        from api.queue.manager import TaskManager
        from api.workers.tier4_telemetry.populate_session_telemetry import populate_session_telemetry
        TaskManager.enqueue_if_needed(
            task_key=f"telemetry_session_cache:{int(year)}:{int(round_number)}:{normalized_session}",
            task_fn=populate_session_telemetry,
            year=int(year),
            round_number=int(round_number),
            session_type=normalized_session,
        )
    
    # Return None so `handle_data_request` triggers the SSE Stream
    return None


def extract_telemetry_overlay(
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
    normalized_session = str(session).upper()
    if not driver_a or not driver_b:
        raise ValueError("driver_a and driver_b are required for telemetry overlay")

    normalized_driver_a = str(driver_a).upper()
    normalized_driver_b = str(driver_b).upper()

    telemetry_session, readiness = _load_session_with_readiness(
        year=year,
        round_number=round_number,
        session=normalized_session,
        telemetry=True,
        weather=False,
        messages=False,
        required_data=("telemetry", "laps"),
    )

    if not readiness.get("can_proceed"):
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
                "driver_a": normalized_driver_a, "driver_b": normalized_driver_b,
                "lap_a": lap_a if lap_a else None, "lap_b": lap_b if lap_b else None,
                "limit_points": limit_points, "stride": stride,
                "sector_start": sector_start, "sector_end": sector_end,
            },
            "traces": [],
        }

    lap_num_a, df_a = _extract_driver_lap_telemetry(
        telemetry_session, normalized_driver_a, lap_a, limit_points or _MAX_TELEMETRY_POINTS, stride, sector_start, sector_end
    )
    lap_num_b, df_b = _extract_driver_lap_telemetry(
        telemetry_session, normalized_driver_b, lap_b, limit_points or _MAX_TELEMETRY_POINTS, stride, sector_start, sector_end
    )

    traces = [
        {"driver": normalized_driver_a, "lap": lap_num_a, "data": _telemetry_rows_from_frame(df_a)},
        {"driver": normalized_driver_b, "lap": lap_num_b, "data": _telemetry_rows_from_frame(df_b)},
    ]

    return {
        "meta": {
            "year": int(year), "round": int(round_number),
            "session": normalized_session,
            "row_count": sum(len(t["data"]) for t in traces),
            "limit_max": _MAX_TELEMETRY_POINTS, **readiness,
        },
        "filters_applied": {
            "driver_a": normalized_driver_a, "driver_b": normalized_driver_b,
            "lap_a": lap_num_a, "lap_b": lap_num_b,
            "limit_points": limit_points, "stride": stride,
            "sector_start": sector_start, "sector_end": sector_end,
        },
        "traces": traces,
    }


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

    if lap is not None and lap < 1:
        raise ValueError("lap must be a positive integer")

    if stride < 1:
        raise ValueError("stride must be a positive integer")

    _validate_sector_window(sector_start, sector_end)

    summaries = []
    
    def _calc_summary(lap_data, drv_code, lap_num):
        speeds = lap_data.get("speed", [])
        brakes = lap_data.get("brake", [])
        throttles = lap_data.get("throttle", [])
        if not speeds:
            return None
        max_speed = round(max(speeds), 2)
        brake_edges = sum(1 for i in range(1, len(brakes)) if brakes[i] and not brakes[i - 1])
        throttle_on_pct = round(sum(1 for t in throttles if t >= 90) / len(throttles) * 100.0, 2) if throttles else None
        return {
            "driver_code": drv_code,
            "lap_number": lap_num,
            "max_speed_kph": max_speed,
            "braking_zones": brake_edges,
            "throttle_on_percentage": throttle_on_pct,
            "samples": len(speeds),
        }

    if driver:
        normalized_driver = str(driver).upper()
        if lap is not None:
            lap_data = get_persisted_lap_telemetry(year, round_number, normalized_session, normalized_driver, lap)
            if lap_data:
                s = _calc_summary(lap_data, normalized_driver, lap)
                if s: summaries.append(s)
        else:
            driver_data = get_persisted_driver_telemetry(year, round_number, normalized_session, normalized_driver)
            if driver_data:
                for lap_key in sorted(driver_data.keys(), key=lambda x: int(x)):
                    s = _calc_summary(driver_data[lap_key], normalized_driver, int(lap_key))
                    if s: summaries.append(s)
    else:
        session_payload = get_persisted_session_telemetry(year, round_number, normalized_session)
        if session_payload:
            for item in session_payload:
                drv = item["driver_code"]
                drv_payload = item["payload"]
                if lap is not None:
                    lap_payload = drv_payload.get(str(lap))
                    if lap_payload:
                        s = _calc_summary(lap_payload, drv, lap)
                        if s: summaries.append(s)
                else:
                    for lap_key in sorted(drv_payload.keys(), key=lambda x: int(x)):
                        s = _calc_summary(drv_payload[lap_key], drv, int(lap_key))
                        if s: summaries.append(s)

    if summaries:
        readiness = build_readiness(True, ["telemetry_summary_persisted"], [], None)
        return {
            "meta": {
                "year": int(year), "round": int(round_number),
                "session": normalized_session, "row_count": len(summaries), **readiness,
            },
            "filters_applied": {
                "driver": driver.upper() if driver else None, "lap": int(lap) if lap else None,
                "stride": int(stride), "sector_start": sector_start, "sector_end": sector_end,
            },
            "summary": summaries,
        }

    return None


def get_tyre_strategy_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Return normalized tyre strategy analysis rows."""
    normalized_session = str(session).upper()
    if normalized_session not in _ALLOWED_SESSIONS:
        raise ValueError("session must be one of R, Q, FP1, FP2, FP3")

    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    if limit is not None:
        limit = min(limit, _MAX_LIMIT)

    normalized_driver = str(driver).upper() if driver else None

    persisted = get_persisted_tyre_strategy_analysis(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver=normalized_driver,
        limit=limit,
    )
    if persisted is not None and persisted.get("data"):
        logger.info(
            "[TyreStrategyView] DB hit year=%s round=%s driver=%s",
            year, round_number, normalized_driver,
        )
        return persisted

    return None


def get_sector_analysis(
    year: int,
    round_number: int,
    session: str = "R",
    driver: Optional[str] = None,
    limit: Optional[int] = None,
):

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

        if normalized_session == "R":
            _session_end = getattr(sector_session, "date", None)
            if _session_end is not None:
                if getattr(_session_end, "tzinfo", None) is None:
                    _session_end = make_aware(_session_end)
                if _session_end < timezone.now():
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
