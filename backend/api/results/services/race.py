"""Service for race results processing."""
import logging
import time
import pandas as pd
from datetime import datetime

from api.common.request_id import get_request_id
from api.queue.manager import TaskManager
from api.results.helpers import (
    _load_session_with_readiness,
    _build_readiness,
    _results_available,
    format_gap,
    format_timedelta
)

logger = logging.getLogger(__name__)


def get_race_session_results(session):
    """
    Get race session results from a loaded session object.
    """
    try:
        race_data = []
        results = session.results.copy()
        
        fastest_laps = None
        fastest_driver_num = None
        
        try:
            if hasattr(session, 'laps') and not session.laps.empty and "LapTime" in session.laps.columns:
                laps = session.laps
                fastest_laps = laps.groupby('DriverNumber')['LapTime'].min().reset_index().rename(columns={'LapTime': 'FastestLap'})
                
                raw_fastest = laps.groupby('DriverNumber')['LapTime'].min()
                if not raw_fastest.empty:
                    fastest_driver_num = raw_fastest.idxmin()
        except Exception as e:
            logger.warning(f"Failed to calculate fastest laps: {e}")
            
        if fastest_laps is not None and not fastest_laps.empty:
            results = results.merge(fastest_laps, on='DriverNumber', how='left')
        else:
            results['FastestLap'] = pd.NaT

        for _, row in results.iterrows():
            position = int(row['Position']) if pd.notna(row.get('Position', None)) else None
            
            gap = None
            raw_gap = row.get('Time') if 'Time' in row else None
            
            if position == 1:
                gap = "LEADER"
            else:
                gap = format_gap(raw_gap, position)
                
            fastest_lap_str = None
            if 'FastestLap' in row:
                fastest_lap_str = format_timedelta(row['FastestLap'])
                
            driver_number_str = str(row['DriverNumber']) if pd.notna(row.get('DriverNumber')) else None
            is_fastest_of_race = (driver_number_str == str(fastest_driver_num)) if fastest_driver_num and driver_number_str else False

            race_info = {
                'position': position,
                'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                'driver_name': row.get('FullName', 'Unknown'),
                'team': row.get('TeamName', 'Unknown'),
                'points': int(row['Points']) if pd.notna(row.get('Points', None)) else 0,
                'status': row.get('Status', 'Unknown'),
                'grid_position': int(row['GridPosition']) if pd.notna(row.get('GridPosition', None)) else None,
                'laps': int(row['Laps']) if pd.notna(row.get('Laps', None)) else 0,
                'gap': gap,
                'fastest_lap': fastest_lap_str,
                'fastest_lap_of_race': is_fastest_of_race,
            }
            race_data.append(race_info)

        return race_data

    except Exception as e:
        raise Exception(f"Error processing race results: {str(e)}")


def get_race_results(year=None, round_number=None):
    """
    Fetch qualifying and race results for a specific round.
    """
    if year is None:
        year = datetime.now().year

    if round_number is None:
        raise ValueError("round_number parameter is required")

    from api.results.services.qualifying import get_qualifying_results

    extract_start = time.time()
    logger.info(
        "event=data_extract_start",
        extra={
            "request_id": get_request_id(),
            "endpoint": "race_results",
            "year": year,
            "round": round_number,
        },
    )

    # Allow tests to patch the legacy `api.services.results` shim; prefer
    # those patched callables when available so unit tests can intercept
    # repository/service calls via the compatibility layer.
    try:
        import importlib

        results_shim = importlib.import_module("api.services.results")
        persisted_fn = getattr(results_shim, "get_persisted_race_results", None)
    except Exception:
        persisted_fn = None

    if persisted_fn is None:
        from api.results.repository import get_persisted_race_results as persisted_fn

    persisted_race_rows = persisted_fn(year, round_number)
    if persisted_race_rows is not None:
        # Prefer shimmed qualifying function when tests patch it.
        try:
            import importlib

            results_shim = importlib.import_module("api.services.results")
            qualifying_fn = getattr(results_shim, "get_qualifying_results", None)
        except Exception:
            qualifying_fn = None

        if qualifying_fn is None:
            from api.results.services.qualifying import get_qualifying_results as qualifying_fn

        qualifying_payload = qualifying_fn(year, round_number)
        if isinstance(qualifying_payload, dict):
            qualifying_rows = qualifying_payload.get("data", [])
            qual_readiness = qualifying_payload.get("meta", {}).get("readiness", _build_readiness(True, ["results"], [], None))
        else:
            qualifying_rows = qualifying_payload
            qual_readiness = _build_readiness(True, ["results"], [], None)

        race_readiness = _build_readiness(True, ["race_results_persisted"], [], None)
        can_proceed = bool(persisted_race_rows or qualifying_rows)
        combined_message = None
        unavailable = []
        if not qual_readiness.get("can_proceed", True):
            unavailable.extend(qual_readiness.get("unavailable_data", []))
            combined_message = qual_readiness.get("message")

        duration_ms = (time.time() - extract_start) * 1000
        logger.info(
            "event=data_extract_complete",
            extra={
                "request_id": get_request_id(),
                "endpoint": "race_results",
                "rows": len(persisted_race_rows),
                "duration_ms": f"{duration_ms:.1f}",
                "source": "cache",
            },
        )

        return {
            'qualifying': qualifying_rows,
            'race': persisted_race_rows,
            'readiness': {
                "can_proceed": can_proceed,
                "available_data": ["race_results_persisted"] + (["qualifying_results"] if qualifying_rows else []),
                "unavailable_data": unavailable,
                "message": combined_message,
                "warnings": ([combined_message] if combined_message else []),
                "components": {
                    "qualifying": qual_readiness,
                    "race": race_readiness,
                },
            },
        }

    try:
        session, race_readiness = _load_session_with_readiness(
            year,
            round_number,
            'R',
            require_results=True,
            require_laps=True,
        )

        race_rows = []
        if race_readiness.get("can_proceed"):
            race_rows = get_race_session_results(session)
        elif session is not None and _results_available(session):
            race_rows = get_race_session_results(session)
            if race_rows:
                race_readiness = _build_readiness(
                    True,
                    ["results"],
                    ["laps"],
                    "Partial race results from session (no lap data).",
                    warnings=["Partial race results from session (no lap data)."],
                )

        try:
            import importlib

            results_shim = importlib.import_module("api.services.results")
            qualifying_fn = getattr(results_shim, "get_qualifying_results", None)
        except Exception:
            qualifying_fn = None

        if qualifying_fn is None:
            from api.results.services.qualifying import get_qualifying_results as qualifying_fn

        qualifying_payload = qualifying_fn(year, round_number)
        if isinstance(qualifying_payload, dict):
            qualifying_rows = qualifying_payload.get("data", [])
            qual_readiness = qualifying_payload.get("meta", {}).get("readiness", _build_readiness(True, ["results"], [], None))
        else:
            qualifying_rows = qualifying_payload
            qual_readiness = _build_readiness(True, ["results"], [], None)

        can_proceed = bool(race_rows or qualifying_rows)
        unavailable = []
        warnings = []
        if not race_readiness.get("can_proceed", True):
            unavailable.extend(race_readiness.get("unavailable_data", []))
            warnings.extend(race_readiness.get("warnings", []))
        if not qual_readiness.get("can_proceed", True):
            unavailable.extend(qual_readiness.get("unavailable_data", []))
            warnings.extend(qual_readiness.get("warnings", []))

        message = warnings[0] if warnings else None

        results_dict = {
            'qualifying': qualifying_rows,
            'race': race_rows,
            'readiness': {
                "can_proceed": can_proceed,
                "available_data": (["race_results"] if race_rows else []) + (["qualifying_results"] if qualifying_rows else []),
                "unavailable_data": unavailable,
                "message": message,
                "warnings": warnings,
                "components": {
                    "qualifying": qual_readiness,
                    "race": race_readiness,
                },
            },
        }

        duration_ms = (time.time() - extract_start) * 1000
        total_rows = len(race_rows) + len(qualifying_rows)
        logger.info(
            "event=data_extract_complete",
            extra={
                "request_id": get_request_id(),
                "endpoint": "race_results",
                "rows": total_rows,
                "duration_ms": f"{duration_ms:.1f}",
                "source": "fastf1_live",
            },
        )

        if race_rows:
            logger.info("event=api_live_fetch_success source=race_results year=%s round=%s session=R row_count=%s", year, round_number, len(race_rows))
        try:
            from django.db import connection
            from django.utils import timezone
            connection.ensure_connection()
            session_end = getattr(session, "date", None)
            if session_end is not None:
                if getattr(session_end, "tzinfo", None) is None:
                    from django.utils.timezone import make_aware
                    session_end = make_aware(session_end)
                if session_end < timezone.now():
                    from api.tasks import populate_race_results as populate_task
                    TaskManager.enqueue_if_needed(
                        task_key=f"race_results:{int(year)}:{int(round_number)}",
                        task_fn=populate_task,
                        year=int(year),
                        round_number=int(round_number),
                        session_type="R",
                    )
        except Exception as e:
            logger.warning("event=persistence_enqueue_failed year=%s round=%s error=%s", year, round_number, e)
        return results_dict

    except Exception as e:
        raise Exception(f"Error fetching F1 race results for {year} Round {round_number}: {str(e)}")
