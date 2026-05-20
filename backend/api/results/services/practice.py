"""Service for practice session processing."""
import logging
import pandas as pd

from api.queue.manager import TaskManager
from api.results.repository import get_persisted_practice_results
from api.results.helpers import (
    _load_session_with_readiness,
    _build_readiness,
    _results_available,
    _practice_rows_from_results
)

logger = logging.getLogger(__name__)


def get_practice_session_results(year, round_number, session_name):
    """
    Get fastest-lap leaderboard for a practice session.
    """
    normalized_session = str(session_name).upper()
    allowed_sessions = {"FP1", "FP2", "FP3"}
    if normalized_session not in allowed_sessions:
        raise ValueError("session_name must be one of FP1, FP2, FP3")

    persisted = get_persisted_practice_results(year, round_number, normalized_session)
    if persisted is not None:
        readiness = _build_readiness(True, ["practice_results_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(persisted),
                "readiness": readiness,
            },
            "data": persisted,
        }

    try:
        session, readiness = _load_session_with_readiness(
            year,
            round_number,
            normalized_session,
            require_results=True,
            require_laps=True,
        )

        if not readiness.get("can_proceed"):
            if session is not None and _results_available(session):
                practice_data = _practice_rows_from_results(session)
                if practice_data:
                    fallback_message = (
                        f"Laps unavailable for {normalized_session}; returning partial practice data from session results."
                    )
                    return {
                        "meta": {
                            "year": int(year),
                            "round": int(round_number),
                            "session": normalized_session,
                            "row_count": len(practice_data),
                            "readiness": _build_readiness(
                                True,
                                readiness.get("available_data", []) or ["results"],
                                readiness.get("unavailable_data", ["laps"]),
                                fallback_message,
                                warnings=[fallback_message],
                            ),
                        },
                        "data": practice_data,
                    }

            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "readiness": readiness,
                },
                "data": [],
            }

        laps = session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if laps.empty:
            if _results_available(session):
                practice_data = _practice_rows_from_results(session)
                if practice_data:
                    fallback_message = f"No lap data available for {normalized_session}; returning partial practice data from session results."
                    readiness = _build_readiness(
                        True,
                        readiness.get("available_data", []) or ["results"],
                        ["laps"],
                        fallback_message,
                        warnings=[fallback_message],
                    )
                    return {
                        "meta": {
                            "year": int(year),
                            "round": int(round_number),
                            "session": normalized_session,
                            "row_count": len(practice_data),
                            "readiness": readiness,
                        },
                        "data": practice_data,
                    }

            readiness = _build_readiness(False, readiness.get("available_data", []), ["laps"], f"No lap data available for {normalized_session}")
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": normalized_session,
                    "row_count": 0,
                    "readiness": readiness,
                },
                "data": [],
            }

        fastest_laps = laps.loc[laps.groupby("Driver")["LapTime"].idxmin()].copy()
        fastest_laps = fastest_laps.sort_values("LapTime")

        practice_data = []
        for position, (_, row) in enumerate(fastest_laps.iterrows(), start=1):
            practice_data.append(
                {
                    "position": position,
                    "driver_code": row.get("Driver", "Unknown"),
                    "team": row.get("Team", "Unknown"),
                    "lap_time": str(row.get("LapTime")) if pd.notna(row.get("LapTime")) else None,
                    "lap_number": int(row.get("LapNumber")) if pd.notna(row.get("LapNumber")) else None,
                }
            )

        logger.info("event=api_live_fetch_success source=practice_results year=%s round=%s session=%s row_count=%s", year, round_number, normalized_session, len(practice_data))
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
                        task_key=f"practice:{int(year)}:{int(round_number)}:{normalized_session}",
                        task_fn=populate_task,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                    )
        except Exception as e:
            logger.warning("event=persistence_enqueue_failed year=%s round=%s error=%s", year, round_number, e)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": normalized_session,
                "row_count": len(practice_data),
                "readiness": readiness,
            },
            "data": practice_data,
        }

    except Exception as e:
        raise Exception(
            f"Error fetching practice results for {year} Round {round_number} {normalized_session}: {str(e)}"
        )
