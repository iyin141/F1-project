"""
F1 Constructors Service
Fetches constructor (team) standings data using Ergast Developer API.
"""
import logging
import requests

from api.services.persistence import get_persisted_constructor_standings
from api.tasks import populate_constructor_standings
from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


API_URLS = [
    "https://ergast.com/api/f1/{year}/constructorStandings.json",
    "https://api.jolpi.ca/ergast/f1/{year}/constructorStandings.json",
]

REQUEST_HEADERS = {
    "User-Agent": "f1-project/1.0 (Django backend)",
    "Accept": "application/json",
}


def _build_readiness(can_proceed, available_data, unavailable_data, message=None):
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": [] if can_proceed else ([message] if message else []),
    }


def get_constructor_standings(year):
    """
    Fetch the F1 constructor standings for a given year from Ergast API.

    Args:
        year (int): The season year.

    Returns:
        dict: Readiness-aware payload with meta and constructor standings rows
    """
    if year is None:
        raise ValueError("year is required")

    persisted = get_persisted_constructor_standings(year)
    if persisted is not None:
        return {
            "meta": {
                "year": int(year),
                "row_count": len(persisted),
                "readiness": _build_readiness(True, ["constructor_standings_persisted"], [], None),
            },
            "data": persisted,
        }

    data = None
    last_error = None
    for template in API_URLS:
        url = template.format(year=year)
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            if response.status_code == 200:
                data = response.json()
                break
            last_error = f"{url} returned status {response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{url} failed: {exc}"

    if data is None:
        message = f"Standings API unavailable: {last_error}"
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": _build_readiness(
                    False,
                    [],
                    ["constructor_standings_api"],
                    message,
                ),
            },
            "data": [],
        }

    standings_list = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")

    if not standings_list:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": _build_readiness(
                    False,
                    [],
                    ["constructor_standings_api"],
                    f"No constructor standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    constructor_standings = standings_list[0].get("ConstructorStandings", [])

    rows = [
        {
            "position": int(c.get("position", 0)),
            "constructor_name": c.get("Constructor", {}).get("name", ""),
            "points": float(c.get("points", 0)),
            "wins": int(c.get("wins", 0)),
        }
        for c in constructor_standings
    ]

    if not rows:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": _build_readiness(
                    False,
                    [],
                    ["constructor_standings_api"],
                    f"No constructor standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    logger.info("event=api_live_fetch_success source=constructor_standings year=%s row_count=%s", year, len(rows))
    TaskManager.enqueue_if_needed(
        task_key=f"constructor_standings:{int(year)}",
        task_fn=populate_constructor_standings,
        year=int(year),
    )
    return {
        "meta": {
            "year": int(year),
            "row_count": len(rows),
            "readiness": _build_readiness(True, ["constructor_standings_api"], [], None),
        },
        "data": rows,
    }
