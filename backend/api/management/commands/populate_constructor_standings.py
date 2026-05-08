"""Populate ConstructorStandings for a season year from Jolpica/Ergast API."""
from __future__ import annotations

import logging
import requests
from django.core.management.base import BaseCommand

from api.models import ConstructorStandings
from api.services.store import store_constructor_standings

_API_URLS = [
    "https://api.jolpi.ca/ergast/f1/{year}/constructorStandings.json",
    "https://ergast.com/api/f1/{year}/constructorStandings.json",
]

_REQUEST_HEADERS = {
    "User-Agent": "f1-project/1.0 (Django backend)",
    "Accept": "application/json",
}

logger = logging.getLogger(__name__)


def run(year: int, force: bool = False) -> int:
    """
    Fetch constructor standings from Jolpica/Ergast and persist to ConstructorStandings.
    Returns the number of rows stored. Returns 0 if already stored and not forced.
    Raises ValueError on failure.
    """
    if not force:
        if ConstructorStandings.objects.filter(year=year).exists():
            logger.info("event=skipped command=populate_constructor_standings year=%s reason=already_stored", year)
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
        raise ValueError(f"Constructor standings API unavailable: {last_error}")

    standings_list = (
        data.get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists")
    )
    if not standings_list:
        raise ValueError(f"No constructor standings data returned for {year}.")

    constructor_standings = standings_list[0].get("ConstructorStandings", [])
    if not constructor_standings:
        raise ValueError(f"Empty ConstructorStandings list for {year}.")

    rows = [
        {
            "position": int(c.get("position", 0)),
            "constructor_name": c.get("Constructor", {}).get("name", ""),
            "points": float(c.get("points", 0)),
            "wins": int(c.get("wins", 0)),
        }
        for c in constructor_standings
    ]

    store_constructor_standings(year, rows)
    logger.info("event=completed command=populate_constructor_standings year=%s row_count=%s", year, len(rows))
    return len(rows)


class Command(BaseCommand):
    help = "Populate ConstructorStandings for a season year from Jolpica/Ergast API."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--force", action="store_true", help="Overwrite existing ConstructorStandings row")

    def handle(self, *args, **options):
        year = options["year"]
        force = options["force"]
        logger.info("event=command_started command=populate_constructor_standings year=%s force=%s", year, force)
        row_count = run(year=year, force=force)
        if row_count:
            self.stdout.write(self.style.SUCCESS(f"Stored constructor standings year={year} | {row_count} entries"))
        else:
            self.stdout.write(f"Skipping year={year}: constructor standings already stored (use --force to overwrite).")
