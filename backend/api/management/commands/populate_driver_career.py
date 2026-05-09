"""Populate DriverCareer for a driver from DB + Jolpica."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import DriverCareer
from api.services.driver_career_service import DriverCareerService
from api.services.store import store_driver_career

logger = logging.getLogger(__name__)

# How long to wait before re-fetching the current year's career data.
# Prevents hammering Jolpica when multiple users view the same driver's profile.
_REFRESH_COOLDOWN = timedelta(hours=1)


def _current_year_needs_refresh(record: DriverCareer) -> bool:
    """
    Decide whether a stored career row needs a current-year refresh.

    Rules:
    - If the stored payload has no entry for the current year → the driver is
      active this season but the row is stale → refresh.
    - If the stored payload already has the current year AND the row was updated
      within the cooldown window → skip (avoid hammering Jolpica).
    - Otherwise (current year present but row is old) → refresh.
    """
    current_year = timezone.now().year

    # Check whether the payload already has a season entry for this year
    career_seasons = (record.payload or {}).get("career", [])
    years_in_payload = {s.get("year") for s in career_seasons if isinstance(s, dict)}
    has_current_year = current_year in years_in_payload

    if not has_current_year:
        # Active driver with no current-year season yet → always refresh
        return True

    # Current year is present — respect the cooldown
    age = timezone.now() - record.updated_at
    if age < _REFRESH_COOLDOWN:
        return False  # Updated very recently, skip

    return True  # Stale current-year data, refresh


def run(driver_code: str, force: bool = False) -> int:
    """
    Fetch driver career history from Jolpica and persist to DriverCareer.

    Skip logic:
    - Historical drivers (no current-year season) → skip if row exists.
    - Active drivers (current-year season present or missing) → refresh
      unless the row was updated within the last hour.
    - force=True → always fetch and overwrite.

    Returns the number of seasons stored, or 0 if skipped.
    Raises ValueError when Jolpica returns no data.
    """
    normalized_code = str(driver_code).upper()
    current_year = timezone.now().year

    if not force:
        existing = DriverCareer.objects.filter(driver_code=normalized_code).first()
        if existing is not None:
            if _current_year_needs_refresh(existing):
                logger.info(
                    "event=refreshing_current_year command=populate_driver_career driver=%s year=%s",
                    normalized_code, current_year,
                )
                # Fall through to fetch + store below
            else:
                logger.info(
                    "event=skipped command=populate_driver_career driver=%s reason=already_current",
                    normalized_code,
                )
                return 0

    service = DriverCareerService()
    career_data = service.get_driver_career(normalized_code, skip_cache=True)

    if not career_data.get("career"):
        raise ValueError(f"No career data available for {normalized_code}.")

    store_driver_career(
        driver_code=normalized_code,
        driver_name=career_data.get("driver_name"),
        nationality=career_data.get("nationality"),
        career_seasons=career_data.get("career", []),
        career_totals=career_data.get("career_totals", {}),
    )

    season_count = len(career_data.get("career", []))
    logger.info(
        "event=completed command=populate_driver_career driver=%s seasons=%s",
        normalized_code, season_count,
    )
    return season_count


class Command(BaseCommand):
    help = "Populate DriverCareer for a driver (DB-first with Jolpica fallback)."

    def add_arguments(self, parser):
        parser.add_argument("--driver", type=str, required=True, dest="driver_code", help="3-letter driver code, e.g. VER")
        parser.add_argument("--force", action="store_true", help="Overwrite existing DriverCareer row")

    def handle(self, *args, **options):
        driver_code = str(options["driver_code"]).upper()
        force = options["force"]
        logger.info("event=command_started command=populate_driver_career driver=%s force=%s", driver_code, force)
        season_count = run(driver_code=driver_code, force=force)
        if season_count:
            self.stdout.write(self.style.SUCCESS(f"Stored career for {driver_code} | {season_count} seasons"))
        else:
            self.stdout.write(f"Skipping driver={driver_code}: career already stored (use --force to overwrite).")
