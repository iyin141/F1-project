"""
Backward-compatibility shim for driver career service.
Provides a thin compatibility layer exposing the legacy
DriverCareerService surface expected by older unit tests.

Where possible this delegates to the new `api.drivers.services` APIs,
but also exposes parsing helpers and module-level symbols (e.g. `requests`,
`RaceResultData`) so tests can patch them.
"""
import logging
from datetime import datetime
import requests

from api.models import RaceResultData
from api.drivers.services.career import get_driver_career
from api.drivers.jolpica_client import resolve_driver_id

logger = logging.getLogger(__name__)


class DriverCareerService:
    """Compatibility wrapper exposing legacy API surface for tests."""

    def get_driver_career(self, driver_code, skip_cache=False):
        return get_driver_career(driver_code, skip_cache)

    def get_driver_season(self, driver_code, year):
        # Delegate to new service where possible
        from api.drivers.services.season import get_driver_season as _svc

        return _svc(driver_code, year)

    # --- Legacy helper methods used directly by unit tests ---
    def _parse_driver_standing_payload(self, payload: dict, driver_code: str) -> list:
        lists = payload.get('MRData', {}).get('StandingsTable', {}).get('StandingsLists', [])
        parsed = []
        for sl in lists:
            season = sl.get('season')
            try:
                year = int(season) if season else None
            except Exception:
                year = None

            for ds in sl.get('DriverStandings', []) or []:
                driver = ds.get('Driver', {})
                code = (driver.get('code') or '').upper()
                if code != (driver_code or '').upper():
                    continue

                constructor = None
                ctors = ds.get('Constructors') or []
                if ctors:
                    constructor = ctors[0].get('name')

                driver_name = f"{driver.get('givenName','')} {driver.get('familyName','')}".strip()
                parsed.append(
                    {
                        'year': year,
                        'driver_name': driver_name,
                        'constructor': constructor,
                        'wins': int(ds.get('wins') or 0),
                        'points': float(ds.get('points') or 0),
                    }
                )
        return parsed

    def _get_schedule_from_jolpica(self, year: int) -> list:
        # Call the Ergast/Jolpica schedule endpoint and return simplified race rows.
        url = f"https://ergast.com/api/f1/{int(year)}.json"
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
        out = []
        for r in races:
            out.append(
                {
                    'round': int(r.get('round') or 0),
                    'race_name': r.get('raceName'),
                    'date': r.get('date'),
                    'location': r.get('Circuit', {}).get('Location', {}).get('locality'),
                    'country': r.get('Circuit', {}).get('Location', {}).get('country'),
                }
            )
        return out

    def _get_round_result(self, driver_code: str, year: int, round_number: int, fallback_results: dict | None = None):
        # Try persisted results first
        try:
            row = RaceResultData.objects.filter(year=year, round_number=round_number).first()
            if row:
                payload = getattr(row, 'payload', {}) or {}
                for r in payload.get('results', []):
                    if r.get('driver_code') == driver_code or str(r.get('driver_number')) == str(driver_code):
                        return r
        except Exception:
            # Persistence not available or mocked; fall through to fallback
            pass

        if fallback_results:
            return fallback_results.get(round_number)
        return None

    def _resolve_driver_id(self, driver_code: str, year: int | None = None) -> str | None:
        # Prefer Jolpica client resolution, tests may patch this method.
        return resolve_driver_id(driver_code, year)

    def _get_career_from_jolpica(self, driver_code: str) -> list:
        # Walk back from the current year to find seasons containing standings for driver_code.
        seasons = []
        current_year = datetime.now().year
        for y in range(current_year, 1949, -1):
            try:
                url = f"https://ergast.com/api/f1/{y}/driverStandings.json"
                resp = requests.get(url)
                resp.raise_for_status()
                payload = resp.json()
                parsed = self._parse_driver_standing_payload(payload, driver_code)
                if parsed:
                    seasons.extend(parsed)
                    break
            except Exception:
                continue
        return seasons
