"""Populate SeasonSchedule for a given year from FastF1."""
from __future__ import annotations

import logging
import pandas as pd
from django.core.management.base import BaseCommand

from api.models import SeasonSchedule
from api.services.fastf1_runtime import fastf1
from api.services.store import store_season_schedule

logger = logging.getLogger(__name__)


def run(year: int, force: bool = False) -> int:
    """
    Fetch season schedule from FastF1 and persist to SeasonSchedule.
    Returns the number of races stored. Returns 0 if already stored and not forced.
    Raises ValueError on failure.
    """
    if not force:
        if SeasonSchedule.objects.filter(year=year).exists():
            logger.info("event=skipped command=populate_schedule year=%s reason=already_stored", year)
            return 0

    try:
        schedule = fastf1.get_event_schedule(year)
    except Exception as exc:
        raise ValueError(f"Failed to load FastF1 schedule for {year}: {exc}")

    races = []
    for _, row in schedule.iterrows():
        if pd.isna(row["RoundNumber"]) or row["RoundNumber"] == 0:
            continue

        def _fmt_dt(val):
            if pd.isna(val):
                return None
            return val.strftime("%Y-%m-%dT%H:%M:%SZ")

        races.append({
            "round": int(row["RoundNumber"]),
            "name": row["EventName"],
            "date": row["EventDate"].strftime("%Y-%m-%d") if pd.notna(row["EventDate"]) else None,
            "location": row.get("Location"),
            "country": row.get("Country"),
            "event_format": row.get("EventFormat"),
            "session1": row.get("Session1"),
            "session1_date_utc": _fmt_dt(row.get("Session1DateUtc")),
            "session2": row.get("Session2"),
            "session2_date_utc": _fmt_dt(row.get("Session2DateUtc")),
            "session3": row.get("Session3"),
            "session3_date_utc": _fmt_dt(row.get("Session3DateUtc")),
            "session4": row.get("Session4"),
            "session4_date_utc": _fmt_dt(row.get("Session4DateUtc")),
            "session5": row.get("Session5"),
            "session5_date_utc": _fmt_dt(row.get("Session5DateUtc")),
        })

    if not races:
        raise ValueError(f"No races found in FastF1 schedule for {year}.")

    store_season_schedule(year, races)
    logger.info("event=completed command=populate_schedule year=%s race_count=%s", year, len(races))
    return len(races)


class Command(BaseCommand):
    help = "Populate SeasonSchedule for a season year from FastF1."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--force", action="store_true", help="Overwrite existing SeasonSchedule row")

    def handle(self, *args, **options):
        year = options["year"]
        force = options["force"]
        logger.info("event=command_started command=populate_schedule year=%s force=%s", year, force)
        race_count = run(year=year, force=force)
        if race_count:
            self.stdout.write(self.style.SUCCESS(f"Stored season schedule year={year} | {race_count} races"))
        else:
            self.stdout.write(f"Skipping year={year}: schedule already stored (use --force to overwrite).")
