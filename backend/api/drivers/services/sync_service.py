"""
Driver sync service — fetch drivers from Jolpica, cache in DB.

DriverSyncService coordinates:
  1. Fetching drivers from Jolpica API (1950–2025)
  2. Upserting to F1Driver model (idempotent)
  3. DB-first search + Jolpica fallback for backward compatibility
  4. Rate limiting (0.3s between requests to respect 4 req/sec burst limit)
"""
import logging
import time
from typing import Optional
import requests
from django.db.models import Q
from api.models.drivers import F1Driver

logger = logging.getLogger(__name__)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
REQUEST_TIMEOUT = 20


class DriverSyncService:
    """Service for syncing F1 drivers from Jolpica into F1Driver model."""

    def sync_season_drivers(self, year: int) -> dict:
        """
        Fetch all drivers for a season from Jolpica and upsert to DB.

        Args:
            year: Season year (e.g., 2025)

        Returns:
            dict: {"year": Y, "synced": N, "errors": E, "message": "..."}
        """
        try:
            url = f"{JOLPICA_BASE}/{year}/drivers.json?limit=100"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            drivers = (
                response.json()
                .get("MRData", {})
                .get("DriverTable", {})
                .get("Drivers", [])
            )
        except Exception as e:
            logger.error(f"[Sync] Failed to fetch drivers for {year}: {e}")
            return {"year": year, "synced": 0, "errors": 1, "message": str(e)}

        synced = 0
        errors = 0

        for d in drivers:
            driver_id = d.get("driverId")
            if not driver_id:
                continue

            try:
                record, created = F1Driver.objects.get_or_create(
                    driver_id=driver_id,
                    defaults={
                        "code": d.get("code") or None,
                        "number": d.get("permanentNumber") or None,
                        "given_name": d.get("givenName", ""),
                        "family_name": d.get("familyName", ""),
                        "nationality": d.get("nationality") or None,
                        "dob": d.get("dateOfBirth") or None,
                        "seasons": [year],
                    },
                )

                if not created:
                    updated = False

                    # Update code/number if they've gained one since last sync
                    new_code = d.get("code") or None
                    new_number = d.get("permanentNumber") or None

                    if new_code and record.code != new_code:
                        record.code = new_code
                        updated = True

                    if new_number and record.number != new_number:
                        record.number = new_number
                        updated = True

                    # Add year to seasons list if not already there
                    if year not in record.seasons:
                        record.seasons = sorted(record.seasons + [year])
                        updated = True

                    if updated:
                        record.save()

                synced += 1
                logger.info(f"[Sync] {'Created' if created else 'Updated'} {driver_id} ({year})")

            except Exception as e:
                logger.error(f"[Sync] Failed to upsert {driver_id}: {e}")
                errors += 1

        return {"year": year, "synced": synced, "errors": errors}

    def sync_all_seasons(self, start: int = 1950, end: int = 2025) -> dict:
        """
        Sync drivers for every season — run once on setup.

        Args:
            start: Start year (default: 1950)
            end: End year (default: 2025)

        Returns:
            dict: {"start": S, "end": E, "total_synced": N, "total_errors": E}
        """
        total_synced = 0
        total_errors = 0

        for year in range(start, end + 1):
            result = self.sync_season_drivers(year)
            total_synced += result.get("synced", 0)
            total_errors += result.get("errors", 0)
            logger.info(f"[Sync] {year} complete: {result['synced']} drivers")
            time.sleep(0.3)  # Stay under 4 req/sec burst limit

        return {
            "start": start,
            "end": end,
            "total_synced": total_synced,
            "total_errors": total_errors,
        }

    def search_drivers(self, query: str, year: Optional[int] = None) -> list:
        """
        Search F1Driver table — DB first, Jolpica fallback if empty.

        Args:
            query: Search string (min 2 chars)
            year: Optional year filter (searches seasons JSONField)

        Returns:
            list: Up to 20 matching driver dicts
        """
        query = query.strip()
        if len(query) < 2:
            return []

        qs = F1Driver.objects.all()

        # Filter by year using seasons JSONField
        if year:
            qs = qs.filter(seasons__contains=year)

        # Search name, code, number, driver_id
        qs = qs.filter(
            Q(given_name__icontains=query)
            | Q(family_name__icontains=query)
            | Q(code__icontains=query)
            | Q(number__icontains=query)
            | Q(driver_id__icontains=query)
        )[:20]

        if qs.exists():
            return [self._serialize(d) for d in qs]

        # Fallback to Jolpica if DB is empty
        logger.warning(f"[Search] DB empty for '{query}', falling back to Jolpica")
        return self._search_jolpica(query, year)

    def get_driver(self, driver_id: str) -> Optional[dict]:
        """
        Get single driver by driverId — DB first, Jolpica fallback.

        Args:
            driver_id: Jolpica driver ID (e.g., "max_verstappen")

        Returns:
            dict or None: Driver dict if found
        """
        try:
            return self._serialize(F1Driver.objects.get(driver_id=driver_id))
        except F1Driver.DoesNotExist:
            return self._fetch_single_from_jolpica(driver_id)

    def _serialize(self, record: F1Driver) -> dict:
        """
        Serialize F1Driver model to standardized response dict.

        Returns:
            dict: Standardized driver dict (no empty strings, use None instead)
        """
        return {
            "driver_id": record.driver_id,
            "code": record.code or None,
            "number": record.number or None,
            "name": record.full_name,
            "given_name": record.given_name,
            "family_name": record.family_name,
            "nationality": record.nationality,
            "dob": record.dob,
            "seasons": record.seasons,
        }

    def _search_jolpica(self, query: str, year: Optional[int] = None) -> list:
        """
        Jolpica fallback when DB has no data.

        Args:
            query: Search string
            year: Optional year filter

        Returns:
            list: Up to 20 matching driver dicts from Jolpica
        """
        try:
            url = (
                f"{JOLPICA_BASE}/{year}/drivers.json?limit=100"
                if year
                else f"{JOLPICA_BASE}/drivers.json?limit=100"
            )
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            drivers = (
                response.json()
                .get("MRData", {})
                .get("DriverTable", {})
                .get("Drivers", [])
            )

            q = query.lower()
            return [
                {
                    "driver_id": d.get("driverId"),
                    "code": d.get("code") or None,
                    "number": d.get("permanentNumber") or None,
                    "name": f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                    "given_name": d.get("givenName"),
                    "family_name": d.get("familyName"),
                    "nationality": d.get("nationality") or None,
                    "dob": d.get("dateOfBirth") or None,
                    "seasons": [],
                }
                for d in drivers
                if q in f"{d.get('givenName', '')} {d.get('familyName', '')}".lower()
                or q in (d.get("code") or "").lower()
            ][:20]
        except Exception as e:
            logger.error(f"[Search] Jolpica fallback failed: {e}")
            return []

    def _fetch_single_from_jolpica(self, driver_id: str) -> Optional[dict]:
        """
        Jolpica fallback for single driver lookup.

        Args:
            driver_id: Jolpica driver ID

        Returns:
            dict or None: Driver dict if found
        """
        try:
            url = f"{JOLPICA_BASE}/drivers/{driver_id}.json"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            drivers = (
                response.json()
                .get("MRData", {})
                .get("DriverTable", {})
                .get("Drivers", [])
            )
            if drivers:
                d = drivers[0]
                return {
                    "driver_id": d.get("driverId"),
                    "code": d.get("code") or None,
                    "number": d.get("permanentNumber") or None,
                    "name": f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                    "given_name": d.get("givenName"),
                    "family_name": d.get("familyName"),
                    "nationality": d.get("nationality") or None,
                    "dob": d.get("dateOfBirth") or None,
                    "seasons": [],
                }
        except Exception as e:
            logger.error(f"[Jolpica] Single driver fetch failed for {driver_id}: {e}")
        return None
