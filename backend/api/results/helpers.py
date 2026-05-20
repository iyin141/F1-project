"""Helper functions for FastF1 results extraction."""
import logging
import time

import pandas as pd
from api.common.readiness import build_readiness, classify_fastf1_exception
from api.common.request_id import get_request_id
from api.services.unified_service import SessionManager

logger = logging.getLogger(__name__)


def _build_readiness(can_proceed, available_data, unavailable_data, message=None, warnings=None):
    return build_readiness(can_proceed, available_data, unavailable_data, message, warnings)


def _dataset_available(session, attr_name):
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


def _laps_available(session):
    if not _dataset_available(session, "laps"):
        return False
    laps = session.laps
    return "LapTime" in laps.columns and bool(laps["LapTime"].notna().any())


def _results_available(session):
    return _dataset_available(session, "results")


def _practice_rows_from_results(session):
    rows = []
    results = getattr(session, "results", None)
    if results is None or results.empty:
        return rows

    sorted_results = results.copy()
    if "Position" in sorted_results.columns:
        sorted_results = sorted_results.sort_values("Position", na_position="last")

    for position, (_, row) in enumerate(sorted_results.iterrows(), start=1):
        lap_time = None
        for field_name in ("LapTime", "BestLapTime", "Time", "Q3", "Q2", "Q1"):
            value = row.get(field_name)
            if pd.notna(value):
                lap_time = str(value)
                break

        rows.append(
            {
                "position": int(row["Position"]) if pd.notna(row.get("Position", None)) else position,
                "driver_code": str(row.get("Abbreviation") or row.get("Driver") or row.get("FullName") or "Unknown"),
                "team": str(row.get("TeamName") or row.get("Team") or "Unknown"),
                "lap_time": lap_time,
                "lap_number": int(row["LapNumber"]) if pd.notna(row.get("LapNumber", None)) else None,
            }
        )

    return rows


def _load_session_with_readiness(year, round_number, session_type, *, telemetry=False, weather=False, messages=False, require_laps=False, require_results=False):
    # Build minimal required_types list for selective loading
    required_types = []
    if telemetry:
        required_types.append("telemetry")
    if weather:
        required_types.append("weather")
    if messages:
        required_types.append("incidents")  # messages map to incidents
    if require_laps:
        if "laps" not in required_types:
            required_types.append("laps")
    if require_results:
        required_types.append("results")
    
    logger.info(
        "event=session_load_start",
        extra={
            "request_id": get_request_id(),
            "year": year,
            "round": round_number,
            "session_type": session_type,
            "required_types": required_types,
            "layer": "results_helper",
        },
    )
    
    load_start = time.time()
    
    try:
        session = SessionManager.get_session(
            year=year,
            round_number=round_number,
            session_type=session_type,
            required_types=required_types,
        )
    except Exception as exc:
        duration_ms = (time.time() - load_start) * 1000
        logger.info(
            "event=session_load_failed",
            extra={
                "request_id": get_request_id(),
                "year": year,
                "round": round_number,
                "session_type": session_type,
                "error": str(exc),
                "duration_ms": f"{duration_ms:.1f}",
            },
        )
        required = []
        if require_laps:
            required.append("laps")
        if require_results:
            required.append("results")

        readiness = classify_fastf1_exception(
            exc,
            year=year,
            round_number=round_number,
            session_name=session_type,
            required_data=tuple(required),
        )
        if readiness is not None:
            return None, readiness
        raise

    available = []
    if _laps_available(session):
        available.append("laps")
    if _results_available(session):
        available.append("results")
    if _dataset_available(session, "messages"):
        available.append("messages")
    if _dataset_available(session, "weather"):
        available.append("weather")

    required = []
    if require_laps:
        required.append("laps")
    if require_results:
        required.append("results")

    duration_ms = (time.time() - load_start) * 1000
    logger.info(
        "event=session_load_complete",
        extra={
            "request_id": get_request_id(),
            "year": year,
            "round": round_number,
            "session_type": session_type,
            "available": available,
            "required": required,
            "duration_ms": f"{duration_ms:.1f}",
            "layer": "results_helper",
        },
    )

    unavailable = [item for item in required if item not in available]
    if unavailable:
        message = (
            f"Session loaded, but required data is unavailable for {year} Round {round_number} ({session_type}). "
            f"Missing: {', '.join(unavailable)}."
        )
        return session, _build_readiness(False, available, unavailable, message)

    return session, _build_readiness(True, available, [], None)


def _format_lap_time(td):
    if td is None or pd.isnull(td):
        return None
    try:
        total = td.total_seconds()
        minutes = int(total // 60)
        seconds = total % 60
        return f"{minutes}:{seconds:06.3f}"
    except Exception:
        return str(td)

def format_timedelta(td):
    return _format_lap_time(td)

def format_gap(gap, position):
    if pd.isna(position):
        position = None
    if position == 1:
        return "LEADER"
    if pd.isnull(gap):
        return "+DNF"
    try:
        if hasattr(gap, 'total_seconds'):
            gap_seconds = gap.total_seconds()
            return f"+{gap_seconds:.3f}s"
        else:
            gap_str = str(gap).strip()
            if not gap_str.startswith('+'):
                return f"+{gap_str}"
            return gap_str
    except Exception:
        return "+DNF"
