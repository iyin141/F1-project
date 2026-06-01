"""Jolpica/Ergast HTTP client for driver data.

During unit tests this module will delegate to `api.drivers.fake_jolpica`
when the `USE_FAKE_JOLPICA` environment variable is set (see
`f1_project.settings_test`). The fake client provides deterministic,
small responses and prevents network calls / noisy logs during tests.
"""
from __future__ import annotations

import logging
import os

from api.common.constants import JOLPICA_HEADERS, JOLPICA_TIMEOUT

logger = logging.getLogger(__name__)

USE_FAKE = os.environ.get("USE_FAKE_JOLPICA") in ("1", "true", "True")

if USE_FAKE:
    # Import the test fake implementation and expose its functions directly.
    from api.drivers.fake_jolpica import (  # type: ignore
        fetch_driver_standings,
        get_season_driver_map,
        resolve_driver_id,
        fetch_all_driver_results,
        get_all_champions,
        fetch_season_results,
        fetch_season_qualifying,
        fetch_season_sprint,
    )
else:
    import requests

    # Core Ergast URLs
    STANDINGS_API_URLS = [
        "https://ergast.com/api/f1/{year}/driverStandings.json",
        "https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json",
    ]

    JOLPICA_DRIVERS_URL = "https://api.jolpi.ca/ergast/f1/drivers/"
    JOLPICA_SEASON_URL = "https://api.jolpi.ca/ergast/f1/{year}/"
    JOLPICA_DRIVER_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/results.json"


    KNOWN_DRIVER_CODE_TO_ID = {
        "HAM": "hamilton",
        "VER": "max_verstappen",
        "LEC": "leclerc",
        "SAI": "sainz",
        "NOR": "norris",
        "PIA": "piastri",
        "RUS": "russell",
        "ALO": "alonso",
        "STR": "stroll",
        "ALB": "albon",
        "OCO": "ocon",
        "GAS": "gasly",
        "HUL": "hulkenberg",
        "MAG": "kevin_magnussen",
        "TSU": "tsunoda",
        "LAW": "lawson",
        "BOT": "bottas",
        "ZHO": "zhou",
        "PER": "perez",
    }

    # Simple module-level cache for driver IDs
    _driver_id_cache = dict(KNOWN_DRIVER_CODE_TO_ID)


    def fetch_driver_standings(year: int) -> dict | None:
        """Try each API URL in order and return the raw JSON response dict."""
        last_error = None
        for template in STANDINGS_API_URLS:
            url = template.format(year=year)
            try:
                response = requests.get(url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
                if response.status_code == 200:
                    return response.json()
                last_error = f"{url} returned status {response.status_code}"
            except requests.RequestException as exc:
                last_error = f"{url} failed: {exc}"

        logger.warning("event=driver_standings_api_unavailable year=%s error=%s", year, last_error)
        return None


    def get_season_driver_map(year: int) -> dict:
        """Fetch all drivers for a given season from Jolpica. Returns a dict keyed by driverId."""
        try:
            url = f"https://api.jolpi.ca/ergast/f1/{year}/drivers.json?limit=100"
            response = requests.get(url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            response.raise_for_status()
            drivers = response.json().get('MRData', {}).get('DriverTable', {}).get('Drivers', [])
            logger.info(f"[Jolpica] Fetched {len(drivers)} drivers for season {year}")

            driver_map = {
                d['driverId']: {
                    'name': f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                    'nationality': d.get('nationality'),
                    'code': (d.get('code') or '').upper(),
                }
                for d in drivers
            }
            return driver_map
        except Exception as e:
            logger.warning(f"Could not fetch driver map for {year}: {e}")
            return {}


    def resolve_driver_id(driver_code: str, year: int | None = None) -> str | None:
        """Resolve FIA code (e.g. HAM) to Jolpica driverId (e.g. hamilton)."""
        code = (driver_code or "").upper()
        if code in _driver_id_cache:
            return _driver_id_cache[code]

        if year:
            season_map = get_season_driver_map(year)
            driver_id = next(
                (did for did, info in season_map.items() if info['code'] == code),
                None
            )
            if driver_id:
                _driver_id_cache[code] = driver_id
                return driver_id

        try:
            response = requests.get(JOLPICA_DRIVERS_URL, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            drivers = data.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
            for driver in drivers:
                if (driver.get("code") or "").upper() == code:
                    driver_id = driver.get("driverId")
                    if driver_id:
                        _driver_id_cache[code] = driver_id
                        return driver_id
        except Exception as exc:
            logger.warning(f"Could not resolve driverId for {driver_code}: {exc}")
        return None


    def fetch_all_driver_results(driver_id: str) -> list:
        """Fetch all race results for a driver, paginating through Jolpica."""
        all_races = []
        offset = 0
        limit = 100

        while True:
            did = (driver_id or "").lower()
            url = f"{JOLPICA_DRIVER_RESULTS_URL.format(driver_id=did)}?limit={limit}&offset={offset}"
            try:
                response = requests.get(url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
                response.raise_for_status()
                data = response.json().get('MRData', {})
                total = int(data.get('total', 0))
                races = data.get('RaceTable', {}).get('Races', [])

                all_races.extend(races)

                if offset + limit >= total:
                    break
                offset += limit
            except Exception as e:
                logger.error(f"Pagination error at offset {offset} for {driver_id}: {e}")
                break

        return all_races


    def get_driver_championships(driver_id: str) -> list:
        """Fetch all championship years for a specific driver. Returns list of years."""
        try:
            url = f"https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/driverstandings/1.json?limit=100"
            response = requests.get(url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            response.raise_for_status()
            
            # ── Handle both StandingsLists (modern) and StandingsList (historic) ─
            standings_table = response.json().get('MRData', {}).get('StandingsTable', {})
            lists = (
                standings_table.get('StandingsLists') or    # ← modern years
                standings_table.get('StandingsList') or      # ← some historic years
                []
            )
            
            championship_years = []
            for sl in lists:
                if sl.get('DriverStandings'):
                    season = int(sl.get('season', 0))
                    if season:
                        championship_years.append(season)
                        logger.debug(f"[Championship] {driver_id}: {season}")
            
            logger.info(f"[Championships] {driver_id} has {len(championship_years)} titles")
            return championship_years
        except Exception as e:
            logger.warning(f"Could not fetch championships for {driver_id}: {e}")
            return []


    def fetch_season_results(year: int, driver_id: str) -> list:
        did = (driver_id or "").lower()
        race_url = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{did}/results.json?limit=100"
        try:
            resp = requests.get(race_url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("Jolpica returned status %s for %s", resp.status_code, race_url)
                return []
            race_data = resp.json()
            races = race_data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
            if not races:
                logger.debug("Jolpica returned empty races for %s", race_url)
            return races
        except Exception as exc:
            logger.debug("Error fetching season results for %s: %s", race_url, exc)
            return []


    def fetch_season_qualifying(year: int, driver_id: str) -> list:
        did = (driver_id or "").lower()
        qual_url = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{did}/qualifying.json?limit=100"
        try:
            resp = requests.get(qual_url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("Jolpica returned status %s for %s", resp.status_code, qual_url)
                return []
            qual_data = resp.json()
            races = qual_data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
            if not races:
                logger.debug("Jolpica returned empty qualifying for %s", qual_url)
            return races
        except Exception as exc:
            logger.debug("Error fetching qualifying for %s: %s", qual_url, exc)
            return []


    def fetch_season_sprint(year: int, driver_id: str) -> list:
        did = (driver_id or "").lower()
        sprint_url = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{did}/sprint.json?limit=100"
        try:
            sprint_resp = requests.get(sprint_url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            if sprint_resp.status_code == 200:
                races = sprint_resp.json().get('MRData', {}).get('RaceTable', {}).get('Races', [])
                if not races:
                    logger.debug("Jolpica returned empty sprint data for %s", sprint_url)
                return races
            else:
                logger.debug("Jolpica returned status %s for %s", sprint_resp.status_code, sprint_url)
        except Exception as exc:
            logger.debug("Error fetching sprint for %s: %s", sprint_url, exc)
        return []
