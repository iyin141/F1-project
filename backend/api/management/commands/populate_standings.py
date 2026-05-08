"""Populate DriverStandings row for a given season year from Jolpica/Ergast API."""
from __future__ import annotations

import logging
import requests
from django.core.management.base import BaseCommand

from api.models import DriverStandings
from api.services.store import store_driver_standings

_API_URLS = [
    "https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json",
    "https://ergast.com/api/f1/{year}/driverStandings.json",
]

_REQUEST_HEADERS = {
    "User-Agent": "f1-project/1.0 (Django backend)",
    "Accept": "application/json",
}

logger = logging.getLogger(__name__)


def run(year: int, force: bool = False) -> int:
    """
    Fetch driver standings from Jolpica/Ergast and persist to DriverStandings.
    Returns the number of rows stored. Returns 0 if already stored and not forced.
    Raises ValueError on failure.
    """
    if not force:
        if DriverStandings.objects.filter(year=year, driver_code__isnull=True).exists():
            logger.info("event=skipped command=populate_standings year=%s reason=already_stored", year)
            return 0

    data = None
    last_error = None
    for template in _API_URLS:
        url = template.format(year=year)
        try:
            response = requests.get(url, headers=_REQUEST_HEADERS, timeout=20)
            if response.status_code == 200:
                data = response.json()
                break
            last_error = f"{url} returned status {response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{url} failed: {exc}"

    if data is None:
        raise ValueError(f"Standings API unavailable: {last_error}")

    standings_list = (
        data.get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists")
    )
    if not standings_list:
        raise ValueError(f"No driver standings data returned for {year}.")

    driver_standings = standings_list[0].get("DriverStandings", [])
    if not driver_standings:
        raise ValueError(f"Empty DriverStandings list for {year}.")

    rows = [
        {
            "position": int(d.get("position", 0)),
            "driver_name": (
                f"{d['Driver'].get('givenName', '')} {d['Driver'].get('familyName', '')}".strip()
            ),
            "points": float(d.get("points", 0)),
            "wins": int(d.get("wins", 0)),
            "constructor": d.get("Constructors", [{}])[0].get("name", ""),
        }
        for d in driver_standings
    ]

    store_driver_standings(year, rows)
    logger.info("event=completed command=populate_standings year=%s row_count=%s", year, len(rows))
    return len(rows)


class Command(BaseCommand):
    help = "Populate DriverStandings for a season year from Jolpica/Ergast API."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--force", action="store_true", help="Overwrite existing DriverStandings row")

    def handle(self, *args, **options):
        year = options["year"]
        force = options["force"]
        logger.info("event=command_started command=populate_standings year=%s force=%s", year, force)
        row_count = run(year=year, force=force)
        if row_count:
            self.stdout.write(self.style.SUCCESS(f"Stored driver standings year={year} | {row_count} entries"))
        else:
            self.stdout.write(f"Skipping year={year}: standings already stored (use --force to overwrite).")
