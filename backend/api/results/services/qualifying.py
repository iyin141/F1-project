"""Service for qualifying results processing."""
import logging
import pandas as pd

from api.common.utils import is_round_completed
from api.queue.manager import TaskManager
from api.results.repository import get_persisted_qualifying_results
from api.results.helpers import (
    _load_session_with_readiness,
    _build_readiness,
    format_timedelta
)

logger = logging.getLogger(__name__)


def get_qualifying_results(year, round_number):
    """
    Get qualifying session results for a specific round.
    """
    persisted = get_persisted_qualifying_results(year, round_number)
    if persisted is not None:
        readiness = _build_readiness(True, ["qualifying_results_persisted"], [], None)
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "Q",
                "row_count": len(persisted),
                "readiness": readiness,
            },
            "data": persisted,
        }

    try:
        session, readiness = _load_session_with_readiness(
            year,
            round_number,
            'Q',
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
                    "session": "Q",
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
                    'q1_time': format_timedelta(row.get('Q1')),
                    'q2_time': format_timedelta(row.get('Q2')),
                    'q3_time': format_timedelta(row.get('Q3')),
                }
                qualifying_data.append(qualifying_info)

        logger.info("event=api_live_fetch_success source=qualifying_results year=%s round=%s session=Q row_count=%s", year, round_number, len(qualifying_data))
        if is_round_completed(year, round_number):
            from api.tasks import populate_race_results as populate_task
            TaskManager.enqueue_if_needed(
                task_key=f"qualifying:{int(year)}:{int(round_number)}",
                task_fn=populate_task,
                year=int(year),
                round_number=int(round_number),
                session_type="Q",
            )
        return {
            "meta": {
                "year": int(year),
                "round": int(round_number),
                "session": "Q",
                "row_count": len(qualifying_data),
                "readiness": readiness,
            },
            "data": qualifying_data,
        }

    except Exception as e:
        raise Exception(f"Error fetching qualifying results: {str(e)}")
