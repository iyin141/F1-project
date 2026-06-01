"""Populate DriverSeasonBreakdown for a driver/year from DB + Jolpica."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import DriverSeasonBreakdown
from api.services.driver_career_service import DriverCareerService
from api.services.store import store_driver_season_breakdown

logger = logging.getLogger(__name__)

# How long to wait before re-fetching the current year's season breakdown.
# Prevents hammering Jolpica when multiple users view the same driver's season page.
_REFRESH_COOLDOWN = timedelta(hours=1)


def run(driver_code: str, year: int, force: bool = False) -> int:
    """
    Fetch race-by-race season breakdown from Jolpica and persist to DriverSeasonBreakdown.

    Skip logic:
    - year < CURRENT_YEAR → historical season, results never change → skip if row exists.
    - year == CURRENT_YEAR → standings still changing every race weekend:
        - Row updated within the last hour → skip (Jolpica rate-limit cooldown).
        - Row older than 1 hour, or no row exists → always fetch and overwrite.
    - force=True → always fetch and overwrite regardless of year.

    Returns the number of races stored, or 0 if skipped.
    Raises ValueError when Jolpica returns no data.
    """
    normalized_code = str(driver_code).upper()
    current_year = timezone.now().year

    if not force:
        existing = DriverSeasonBreakdown.objects.filter(
            driver_code=normalized_code, year=year
        ).first()

        if existing is not None:
            if year < current_year:
                # Historical season — race results never change, safe to skip
                logger.info(
                    "event=skipped command=populate_driver_season driver=%s year=%s reason=historical_already_stored",
                    normalized_code, year,
                )
                return 0
            else:
                # Current year — check cooldown before hitting Jolpica again
                age = timezone.now() - existing.updated_at
                if age < _REFRESH_COOLDOWN:
                    logger.info(
                        "event=skipped command=populate_driver_season driver=%s year=%s reason=updated_recently age_seconds=%s",
                        normalized_code, year, int(age.total_seconds()),
                    )
                    return 0
                logger.info(
                    "event=refreshing_current_year command=populate_driver_season driver=%s year=%s",
                    normalized_code, year,
                )
                # Fall through to fetch + store below

    service = DriverCareerService()
    # For fetching, prefer passing through the original identifier for
    # non-3-letter inputs (surnames, Jolpica ids). Only uppercase when
    # the input is a 3-letter FIA code.
    service_identifier = driver_code if not (str(driver_code).isalpha() and len(str(driver_code)) == 3) else normalized_code
    season_data = service.get_driver_season(service_identifier, year)

    if not season_data.get("races"):
        raise ValueError(f"No race data available for {normalized_code} in {year}.")

    # Determine canonical 3-letter FIA code to store. Prefer the canonical
    # code returned by the season service; otherwise, try the DB-backed
    # F1Driver lookup by driver_id; finally, fall back to a safe truncation
    # of the normalized input to avoid DB length errors.
    canonical_code = season_data.get("canonical_code")
    driver_id = season_data.get("driver_id")
    if not canonical_code and driver_id:
        try:
            from api.models.drivers import F1Driver

            f = F1Driver.objects.filter(driver_id__iexact=driver_id).first()
            if f and f.code:
                canonical_code = f.code
        except Exception:
            canonical_code = None

    if not canonical_code:
        # If input was already a 3-letter code, use it; otherwise truncate
        # to 3 chars as a last-resort safe value.
        canonical_code = normalized_code if len(normalized_code) == 3 else normalized_code[:3]

    store_driver_season_breakdown(
        driver_code=canonical_code,
        year=year,
        driver_name=season_data.get("driver_name"),
        constructor=season_data.get("constructor"),
        final_position=season_data.get("final_position"),
        final_points=season_data.get("final_points"),
        races=season_data.get("races", []),
    )

    race_count = len(season_data.get("races", []))
    logger.info(
        "event=completed command=populate_driver_season driver=%s year=%s race_count=%s",
        normalized_code, year, race_count,
    )
    return race_count


class Command(BaseCommand):
    help = "Populate DriverSeasonBreakdown for a driver/year (DB-first with Jolpica fallback)."

    def add_arguments(self, parser):
        parser.add_argument("--driver", type=str, required=True, dest="driver_code", help="3-letter driver code, e.g. VER")
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2023")
        parser.add_argument("--force", action="store_true", help="Overwrite existing DriverSeasonBreakdown row")

    def handle(self, *args, **options):
        driver_code = str(options["driver_code"]).upper()
        year = options["year"]
        force = options["force"]
        logger.info("event=command_started command=populate_driver_season driver=%s year=%s force=%s", driver_code, year, force)
        race_count = run(driver_code=driver_code, year=year, force=force)
        if race_count:
            self.stdout.write(self.style.SUCCESS(f"Stored season breakdown for {driver_code}/{year} | {race_count} races"))
        else:
            self.stdout.write(f"Skipping driver={driver_code} year={year}: season breakdown already stored (use --force to overwrite).")
