"""
F1 Results Service
Fetches race results (qualifying and race) data using FastF1 library.
"""
import logging
import pandas as pd
from datetime import datetime

from .fastf1_runtime import fastf1
from .persistence import (
    get_persisted_practice_results,
    get_persisted_qualifying_results,
    get_persisted_race_results,
    get_persisted_sprint_results,
    get_persisted_sprint_shootout_results,
)
from .readiness import build_readiness, classify_fastf1_exception
from api.tasks import populate_race_results
from api.services.task_manager import TaskManager

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
    try:
        session = fastf1.get_session(year, round_number, session_type)
        session.load(telemetry=telemetry, weather=weather, messages=messages)
    except Exception as exc:
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

    unavailable = [item for item in required if item not in available]
    if unavailable:
        message = (
            f"Session loaded, but required data is unavailable for {year} Round {round_number} ({session_type}). "
            f"Missing: {', '.join(unavailable)}."
        )
        return session, _build_readiness(False, available, unavailable, message)

    return session, _build_readiness(True, available, [], None)


def get_race_results(year=None, round_number=None):
    """
    Fetch qualifying and race results for a specific round.

    Args:
        year (int): The season year. Defaults to current year.
        round_number (int): The round number (1-24, depending on season).

    Returns:
        dict: Contains 'qualifying' and 'race' keys, each with a list of result dictionaries
    """
    if year is None:
        year = datetime.now().year

    if round_number is None:
        raise ValueError("round_number parameter is required")

    persisted_race_rows = get_persisted_race_results(year, round_number)
    if persisted_race_rows is not None:
        qualifying_payload = get_qualifying_results(year, round_number)
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
        # Get the session object for the race
        session, race_readiness = _load_session_with_readiness(
            year,
            round_number,
            'R',
            telemetry=False,
            weather=False,
            messages=False,
            require_results=True,
        )

        race_rows = []
        if race_readiness.get("can_proceed"):
            race_rows = get_race_session_results(session)

        qualifying_payload = get_qualifying_results(year, round_number)
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

        if race_rows:
            logger.info("event=api_live_fetch_success source=race_results year=%s round=%s session=R row_count=%s", year, round_number, len(race_rows))
        TaskManager.enqueue_if_needed(
            task_key=f"race:{int(year)}:{int(round_number)}:R",
            task_fn=populate_race_results,
            year=int(year),
            round_number=int(round_number),
            session_type="R",
        )
        return results_dict

    except Exception as e:
        raise Exception(f"Error fetching F1 race results for {year} Round {round_number}: {str(e)}")


def get_practice_session_results(year, round_number, session_name):
    """
    Get fastest-lap leaderboard for a practice session.

    Args:
        year (int): The season year.
        round_number (int): The round number.
        session_name (str): Practice session name (FP1, FP2, FP3).

    Returns:
        list: Fastest lap result dictionaries for the session.
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
            telemetry=False,
            weather=False,
            messages=False,
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
        TaskManager.enqueue_if_needed(
            task_key=f"race:{int(year)}:{int(round_number)}:{normalized_session}",
            task_fn=populate_race_results,
            year=int(year),
            round_number=int(round_number),
            session_type=normalized_session,
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

    except Exception as e:
        raise Exception(
            f"Error fetching practice results for {year} Round {round_number} {normalized_session}: {str(e)}"
        )


def get_qualifying_results(year, round_number):
    """
    Get qualifying session results for a specific round.

    Args:
        year (int): The season year.
        round_number (int): The round number.

    Returns:
        list: List of qualifying result dictionaries
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
            # Only include drivers who actually set qualifying times
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

        logger.info("event=api_live_fetch_success source=qualifying_results year=%s round=%s session=Q row_count=%s", year, round_number, len(qualifying_data))
        TaskManager.enqueue_if_needed(
            task_key=f"race:{int(year)}:{int(round_number)}:Q",
            task_fn=populate_race_results,
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



def get_sprint_shootout_results(year, round_number):
    """
    Get sprint shootout session results for a specific round.

    Args:
        year (int): The season year.
        round_number (int): The round number.

    Returns:
        dict: Sprint shootout result payload
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
        TaskManager.enqueue_if_needed(
            task_key=f"race:{int(year)}:{int(round_number)}:SQ",
            task_fn=populate_race_results,
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

    Args:
        year (int): The season year.
        round_number (int): The round number.

    Returns:
        dict: Sprint result payload
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
        TaskManager.enqueue_if_needed(
            task_key=f"race:{int(year)}:{int(round_number)}:S",
            task_fn=populate_race_results,
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



def get_race_session_results(session):
    """
    Get race session results from a loaded session object.

    Args:
        session: A FastF1 session object (already loaded).

    Returns:
        list: List of race result dictionaries
    """
    try:
        race_data = []
        results = session.results

        for _, row in results.iterrows():
            race_info = {
                'position': int(row['Position']) if pd.notna(row.get('Position', None)) else None,
                'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                'driver_name': row.get('FullName', 'Unknown'),
                'team': row.get('TeamName', 'Unknown'),
                'points': int(row['Points']) if pd.notna(row.get('Points', None)) else 0,
                'status': row.get('Status', 'Unknown'),
                'grid_position': int(row['GridPosition']) if pd.notna(row.get('GridPosition', None)) else None,
                'laps': int(row['Laps']) if pd.notna(row.get('Laps', None)) else 0,
            }
            race_data.append(race_info)

        return race_data

    except Exception as e:
        raise Exception(f"Error processing race results: {str(e)}")
