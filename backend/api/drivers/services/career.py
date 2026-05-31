"""Driver career service — fetches a driver's full career history."""
from __future__ import annotations

import logging

from api.models import DriverCareer
from api.drivers.repository import get_persisted_driver_career
from api.drivers.jolpica_client import (
    resolve_driver_id,
    fetch_all_driver_results,
)
from api.drivers.repository import resolve_to_jolpica_id
from api.drivers.services.champions_sync_service import ChampionsSyncService

logger = logging.getLogger(__name__)


def get_driver_career(driver_code: str, skip_cache: bool = False) -> dict:
    """Get full career summary for a driver.

    `driver_code` may be a 3-letter FIA code (e.g. 'HAM') or a Jolpica driverId
    (e.g. 'lewis_hamilton' or 'max_verstappen'). Detect Jolpica IDs and avoid
    resolving them again via Jolpica.
    """
    # Detect likely Jolpica driverId patterns (contains underscore/hyphen or longer than 3)
    is_jolpica_id = False
    if driver_code and ("_" in driver_code or "-" in driver_code or len(driver_code) > 3):
        is_jolpica_id = True

    normalized_code = driver_code if is_jolpica_id else (driver_code or "").upper()

    if not skip_cache and not is_jolpica_id:
        cached_data = get_persisted_driver_career(normalized_code)
        if cached_data:
            career = cached_data.get("career", [])
            total_races = sum(c.get("races", 0) for c in career)
            if total_races > 0:
                cached_data["driver_code"] = normalized_code
                return cached_data

    # Resolve identifier to a Jolpica driver_id using repository helper.
    driver_id = resolve_to_jolpica_id(driver_code)
    if not driver_id:
        # fall back to Jolpica resolver for codes not present in local DB
        driver_id = resolve_driver_id(normalized_code) if not is_jolpica_id else None
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
            
            # ── Guard position parsing — handle non-numeric results ─────────
            pos_str = result.get('position', '')
            if not pos_str or not str(pos_str).lstrip('-').isdigit():
                logger.debug(f"Skipping non-numeric position: {pos_str} (year={year})")
                continue
            
            try:
                position = int(pos_str)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to cast position '{pos_str}' for year {year}: {e}")
                continue

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
                logger.debug(f"WIN: {driver_code} P1 in {year}")
            elif position in (2, 3):
                podiums += 1
                by_year[year]['podiums'] += 1
                logger.debug(f"PODIUM: {driver_code} P{position} in {year}")

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
    championship_years = ChampionsSyncService().get_championship_years(driver_id)
    for year in by_year:
        if year in championship_years:
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
