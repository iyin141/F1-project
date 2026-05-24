"""F1 Champions sync service — fetches and persists WDC winners."""
import logging
import time
import requests
from api.models.champions import F1Champion

logger = logging.getLogger(__name__)
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
REQUEST_TIMEOUT = 20


class ChampionsSyncService:
    """Sync F1 champions from Jolpica into F1Champion table."""

    def sync_all_champions(self) -> dict:
        """
        Fetch all-time champions from Jolpica one year at a time
        and upsert into F1Champion table.

        Jolpica has no global champions endpoint so we fetch
        final standings for each year and take P1.
        """
        synced = 0
        errors = 0
        current_year = 2026

        for year in range(1950, current_year + 1):
            result = self.sync_year_champion(year)
            if result.get('synced'):
                synced += 1
            elif result.get('error'):
                errors += 1
            time.sleep(0.25)  # stay under 4 req/sec

        return {
            "total_synced": synced,
            "total_errors": errors,
            "years_covered": f"1950–{current_year}"
        }

    def sync_year_champion(self, year: int) -> dict:
        """Fetch and store champion for a single year."""
        try:
            url = f"{JOLPICA_BASE}/{year}/driverstandings/1.json"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            standings_lists = (
                data.get('MRData', {})
                    .get('StandingsTable', {})
                    .get('StandingsLists') or
                data.get('MRData', {})
                    .get('StandingsTable', {})
                    .get('StandingsList') or
                []
            )

            if not standings_lists:
                logger.warning(f"[Champions] No standings data for {year}")
                return {"year": year, "synced": False}

            standings = standings_lists[0].get('DriverStandings', [])
            if not standings:
                return {"year": year, "synced": False}

            # P1 is the champion
            p1 = standings[0]
            driver = p1.get('Driver', {})
            constructors = p1.get('Constructors', [{}])
            constructor = constructors[0] if constructors else {}

            driver_id = driver.get('driverId')
            if not driver_id:
                return {"year": year, "synced": False}

            F1Champion.objects.update_or_create(
                year=year,
                defaults={
                    "driver_id": driver_id,
                    "driver_code": driver.get('code') or None,
                    "driver_name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                    "team": constructor.get('name') or None,
                    "points": float(p1.get('points', 0)) if p1.get('points') else None,
                    "wins": int(p1.get('wins', 0)) if p1.get('wins') else None,
                }
            )

            logger.info(f"[Champions] {year}: {driver_id}")
            return {"year": year, "synced": True, "driver_id": driver_id}

        except Exception as e:
            logger.error(f"[Champions] Failed for {year}: {e}")
            return {"year": year, "synced": False, "error": str(e)}

    def get_championship_years(self, driver_id: str) -> list:
        """
        Get all years a driver won the championship.
        Pure DB read — no Jolpica call.
        """
        return list(
            F1Champion.objects
            .filter(driver_id=driver_id)
            .values_list('year', flat=True)
            .order_by('year')
        )
