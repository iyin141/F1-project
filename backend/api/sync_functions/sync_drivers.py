"""CLI-callable driver sync functions.

These wrap the existing `DriverSyncService` methods so callers (CLI,
management commands, Celery tasks) can import a plain function.
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Dict, Optional

import requests
from api.models.drivers import F1Driver

logger = logging.getLogger(__name__)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
REQUEST_TIMEOUT = 20


def sync_season_drivers(year: int) -> Dict:
    """Fetch all drivers for a season from Jolpica and upsert to DB.

    Returns same dict shape as the old DriverSyncService.sync_season_drivers.
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

                new_code = d.get("code") or None
                new_number = d.get("permanentNumber") or None

                if new_code and record.code != new_code:
                    record.code = new_code
                    updated = True

                if new_number and record.number != new_number:
                    record.number = new_number
                    updated = True

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


def sync_all_seasons(start: int = 1950, end: int = 2025) -> Dict:
    total_synced = 0
    total_errors = 0

    for year in range(start, end + 1):
        result = sync_season_drivers(year)
        total_synced += result.get("synced", 0)
        total_errors += result.get("errors", 0)
        logger.info(f"[Sync] {year} complete: {result.get('synced', 0)} drivers")
        time.sleep(0.3)

    return {"start": start, "end": end, "total_synced": total_synced, "total_errors": total_errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync F1 drivers from Jolpica")
    parser.add_argument("--year", type=int, help="Sync a specific season")
    parser.add_argument("--all", action="store_true", help="Sync all seasons (use --start/--end)")
    parser.add_argument("--start", type=int, default=1950, help="Start year for --all")
    parser.add_argument("--end", type=int, default=2025, help="End year for --all")

    args = parser.parse_args(argv)

    if args.all:
        logger.info("Starting full sync: %s–%s", args.start, args.end)
        result = sync_all_seasons(start=args.start, end=args.end)
        print(result)
        return 0

    year = args.year or None
    if not year:
        parser.error("either --year or --all must be provided")

    result = sync_season_drivers(year)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
