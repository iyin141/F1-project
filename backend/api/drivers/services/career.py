"""Driver career service — fetches a driver's full career history."""
from __future__ import annotations

import logging

from api.models import DriverCareer
from api.drivers.repository import get_persisted_driver_career
from api.drivers.jolpica_client import (
    resolve_driver_id,
    fetch_all_driver_results,
    get_all_champions,
)

logger = logging.getLogger(__name__)


def get_driver_career(driver_code: str, skip_cache: bool = False) -> dict:
    """Get full career summary for a driver."""
    driver_code = driver_code.upper()

    if not skip_cache:
        cached_data = get_persisted_driver_career(driver_code)
        if cached_data:
            career = cached_data.get("career", [])
            total_races = sum(c.get("races", 0) for c in career)
            if total_races > 0:
                cached_data["driver_code"] = driver_code
                return cached_data

    driver_id = resolve_driver_id(driver_code)
    if not driver_id:
        return {
            "driver_code": driver_code,
            "driver_name": None,
            "nationality": None,
            "career": [],
            "career_totals": {"total_wins": 0, "total_podiums": 0},
            "message": "Driver not found in Jolpica",
        }

    wins = 0
    podiums = 0
    by_year = {}
    driver_name = None
    nationality = None

    try:
        races = fetch_all_driver_results(driver_id)

        for race in races:
            year = int(race.get('season', 0))
            if not year:
                continue

            results = race.get('Results', [])
            if not results:
                continue

            result = results[0]
            position = int(result.get('position', 0))

            if not driver_name:
                driver_info = result.get('Driver', {})
                driver_name = f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip()
                nationality = driver_info.get('nationality')

            if year not in by_year:
                by_year[year] = {'wins': 0, 'podiums': 0, 'races': 0, 'champion': False}

            by_year[year]['races'] += 1

            if position == 1:
                wins += 1
                podiums += 1
                by_year[year]['wins'] += 1
                by_year[year]['podiums'] += 1
            elif position in (2, 3):
                podiums += 1
                by_year[year]['podiums'] += 1

    except Exception as exc:
        logger.error(f"Error fetching Jolpica career data for {driver_code}: {exc}")
        return {
            "driver_code": driver_code,
            "driver_name": None,
            "nationality": None,
            "career": [],
            "career_totals": {"total_wins": 0, "total_podiums": 0, "championships": 0},
            "message": f"Error fetching career data: {exc}",
        }

    championships = 0
    all_champions = get_all_champions()
    for year in by_year:
        if all_champions.get(year) == driver_id:
            by_year[year]['champion'] = True
            championships += 1

    career_data = sorted(
        [
            {
                "year":     year,
                "races":    stats["races"],
                "wins":     stats["wins"],
                "podiums":  stats["podiums"],
                "champion": stats["champion"],
            }
            for year, stats in by_year.items()
        ],
        key=lambda x: x["year"],
        reverse=True,
    )

    result = {
        "driver_code": driver_code,
        "driver_name": driver_name,
        "nationality": nationality,
        "career": career_data,
        "career_totals": {
            "total_wins":    wins,
            "total_podiums": podiums,
            "championships": championships,
        },
        "message": None if career_data else "No career data available",
    }

    if career_data:
        DriverCareer.objects.update_or_create(
            driver_code=driver_code,
            defaults={"payload": result}
        )

    return result
