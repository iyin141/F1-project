"""
F1 Drivers Service
Fetches driver standings data using Ergast Developer API.
"""
import logging
import requests

from .persistence import get_persisted_driver_standings
from api.tasks import populate_standings
from api.services.task_manager import TaskManager
from api.services.utils import is_current_year

logger = logging.getLogger(__name__)

API_URLS = [
    "https://ergast.com/api/f1/{year}/driverStandings.json",
    "https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json",
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


def get_driver_standings(year):
    """
    Fetch the F1 driver standings for a given year from Ergast API.

    Args:
        year (int): The season year.

    Returns:
        list: List of driver standing dictionaries
    """
    if year is None:
        raise ValueError("year is required")

    persisted = get_persisted_driver_standings(year)
    if persisted is not None:
        return {
            "meta": {
                "year": int(year),
                "row_count": len(persisted),
                "readiness": _build_readiness(True, ["driver_standings_persisted"], [], None),
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
                    ["driver_standings_api"],
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
                    ["driver_standings_api"],
                    f"No driver standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    driver_standings = standings_list[0].get("DriverStandings", [])

    rows = [
        {
            "position": int(d.get("position", 0)),
            "driver_name": f"{d['Driver'].get('givenName', '')} {d['Driver'].get('familyName', '')}".strip(),
            "points": float(d.get("points", 0)),
            "wins": int(d.get("wins", 0)),
            "constructor": d.get("Constructors", [{}])[0].get("name", ""),
        }
        for d in driver_standings
    ]

    if not rows:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": _build_readiness(
                    False,
                    [],
                    ["driver_standings_api"],
                    f"No driver standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    logger.info("event=api_live_fetch_success source=driver_standings year=%s row_count=%s", year, len(rows))
    if not is_current_year(year):
        TaskManager.enqueue_if_needed(
            task_key=f"standings:{int(year)}",
            task_fn=populate_standings,
            year=int(year),
        )
    return {
        "meta": {
            "year": int(year),
            "row_count": len(rows),
            "readiness": _build_readiness(True, ["driver_standings_api"], [], None),
        },
        "data": rows,
    }
