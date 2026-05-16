"""Service for weekend results processing."""
import logging

from api.schedule.services import get_race_by_round
from api.results.services.practice import get_practice_session_results
from api.results.services.qualifying import get_qualifying_results
from api.results.services.sprint import get_sprint_shootout_results, get_sprint_results
from api.results.services.race import get_race_results

logger = logging.getLogger(__name__)


def get_weekend_results(year, round_number):
    """
    Get all session results for a race weekend.
    """
    race_info = get_race_by_round(year, round_number)
    if not race_info:
        return None

    sessions_to_fetch = {
        "FP1": {"func": get_practice_session_results, "kwargs": {"session_name": "FP1"}},
        "FP2": {"func": get_practice_session_results, "kwargs": {"session_name": "FP2"}},
        "FP3": {"func": get_practice_session_results, "kwargs": {"session_name": "FP3"}},
        "Q": {"func": get_qualifying_results, "kwargs": {}},
        "SQ": {"func": get_sprint_shootout_results, "kwargs": {}},
        "S": {"func": get_sprint_results, "kwargs": {}},
        "R": {"func": get_race_results, "kwargs": {}},
    }

    scheduled_sessions = []
    for k in ['session1', 'session2', 'session3', 'session4', 'session5']:
        s_name = race_info.get(k)
        if not s_name:
            continue
        s_name = str(s_name).lower()
        if 'practice 1' in s_name: scheduled_sessions.append("FP1")
        elif 'practice 2' in s_name: scheduled_sessions.append("FP2")
        elif 'practice 3' in s_name: scheduled_sessions.append("FP3")
        elif 'sprint shootout' in s_name: scheduled_sessions.append("SQ")
        elif 'sprint qualifying' in s_name: scheduled_sessions.append("SQ")
        elif 'sprint' in s_name: scheduled_sessions.append("S")
        elif 'qualifying' in s_name: scheduled_sessions.append("Q")
        elif 'race' in s_name: scheduled_sessions.append("R")

    if not scheduled_sessions:
        scheduled_sessions = ["FP1", "FP2", "FP3", "Q", "SQ", "S", "R"]

    if "R" not in scheduled_sessions:
        scheduled_sessions.append("R")

    weekend_results = {}

    for session_key in scheduled_sessions:
        if session_key not in sessions_to_fetch:
            continue

        config = sessions_to_fetch[session_key]
        func = config["func"]
        kwargs = {"year": year, "round_number": round_number, **config["kwargs"]}

        try:
            res = func(**kwargs)
            if session_key == "R":
                weekend_results["race_results"] = res
            else:
                if isinstance(res, dict):
                    rows = res.get("data", [])
                    readiness = res.get("meta", {}).get("readiness")
                else:
                    rows = res
                    readiness = None

                weekend_results[session_key] = {
                    "data": rows,
                    "readiness": readiness,
                }

        except Exception as e:
            weekend_results[session_key] = {
                "error": str(e),
                "status": "failed"
            }

    return {
        "year": year,
        "round": round_number,
        "event_format": race_info.get("event_format", "unknown"),
        "sessions": weekend_results
    }
