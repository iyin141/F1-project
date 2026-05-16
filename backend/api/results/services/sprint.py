"""Service for sprint results processing."""
import logging
import pandas as pd

from api.common.utils import is_round_completed
from api.queue.manager import TaskManager
from api.results.repository import get_persisted_sprint_results, get_persisted_sprint_shootout_results
from api.results.helpers import (
    _load_session_with_readiness,
    _build_readiness,
    format_timedelta
)
from api.results.services.race import get_race_session_results

logger = logging.getLogger(__name__)


def get_sprint_shootout_results(year, round_number):
    """
    Get sprint shootout session results for a specific round.
    """
    persisted = get_persisted_sprint_shootout_results(year, round_number)
    if persisted is not None:
        readiness = _build_readiness(True, ["sprint_shootout_results_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "SQ",
                "row_count": len(persisted),
                "readiness": readiness,
            },
            "data": persisted,
        }

    try:
        session, readiness = _load_session_with_readiness(
            year,
            round_number,
            'SQ',
            telemetry=False,
            weather=False,
            messages=True,
            require_results=True,
        )

        if not readiness.get("can_proceed"):
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": "SQ",
                    "row_count": 0,
                    "readiness": readiness,
                },
                "data": [],
            }

        qualifying_data = []
        results = session.results

        for _, row in results.iterrows():
            if pd.notna(row.get('Q1', None)):
                qualifying_info = {
                    'position': int(row['Position']) if pd.notna(row.get('Position', None)) else None,
                    'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                    'driver_name': row.get('FullName', 'Unknown'),
                    'team': row.get('TeamName', 'Unknown'),
                    'q1_time': str(row['Q1']) if pd.notna(row.get('Q1', None)) else None,
                    'q2_time': str(row['Q2']) if pd.notna(row.get('Q2', None)) else None,
                    'q3_time': str(row['Q3']) if pd.notna(row.get('Q3', None)) else None,
                }
                qualifying_data.append(qualifying_info)

        logger.info("event=api_live_fetch_success source=sprint_shootout_results year=%s round=%s session=SQ row_count=%s", year, round_number, len(qualifying_data))
        if is_round_completed(year, round_number):
            from api.tasks import populate_race_results as populate_task
            TaskManager.enqueue_if_needed(
                task_key=f"sprint_shootout:{int(year)}:{int(round_number)}",
                task_fn=populate_task,
                year=int(year),
                round_number=int(round_number),
                session_type="SQ",
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "SQ",
                "row_count": len(qualifying_data),
                "readiness": readiness,
            },
            "data": qualifying_data,
        }

    except Exception as e:
        raise Exception(f"Error fetching sprint shootout results: {str(e)}")


def get_sprint_results(year, round_number):
    """
    Get sprint session results for a specific round.
    """
    persisted = get_persisted_sprint_results(year, round_number)
    if persisted is not None:
        readiness = _build_readiness(True, ["sprint_results_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "S",
                "row_count": len(persisted),
                "readiness": readiness,
            },
            "data": persisted,
        }

    try:
        session, readiness = _load_session_with_readiness(
            year,
            round_number,
            'S',
            telemetry=False,
            weather=False,
            messages=False,
            require_results=True,
        )

        if not readiness.get("can_proceed"):
            return {
                "meta": {
                    "year": int(year),
                    "round": int(round_number),
                    "session": "S",
                    "row_count": 0,
                    "readiness": readiness,
                },
                "data": [],
            }

        race_data = get_race_session_results(session)

        logger.info("event=api_live_fetch_success source=sprint_results year=%s round=%s session=S row_count=%s", year, round_number, len(race_data))
        if is_round_completed(year, round_number):
            from api.tasks import populate_race_results as populate_task
            TaskManager.enqueue_if_needed(
                task_key=f"sprint_results:{int(year)}:{int(round_number)}",
                task_fn=populate_task,
                year=int(year),
                round_number=int(round_number),
                session_type="S",
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "S",
                "row_count": len(race_data),
                "readiness": readiness,
            },
            "data": race_data,
        }

    except Exception as e:
        raise Exception(f"Error fetching sprint results: {str(e)}")
