"""Repository layer for driver data — all ORM queries live here."""
from __future__ import annotations

from api.models import DriverStandings, DriverCareer, DriverSeasonBreakdown


def get_persisted_driver_standings(year: int) -> list[dict] | None:
    """Return the persisted driver standings list for a given year, or None."""
    record = DriverStandings.objects.filter(year=year).first()
    if record is None:
        return None
    rows = record.payload.get("standings", [])
    return rows if rows else None


def get_persisted_driver_career(driver_code: str) -> dict | None:
    """
    Return the persisted DriverCareer payload for a driver, or None.
    Returns the full payload dict: {driver_name, nationality, career, career_totals}.
    """
    normalized_code = str(driver_code).upper()
    record = DriverCareer.objects.filter(driver_code=normalized_code).first()
    if record is None:
        return None
    return dict(record.payload or {})


def get_persisted_driver_season_breakdown(driver_code: str, year: int) -> dict | None:
    """
    Return the persisted DriverSeasonBreakdown payload for (driver_code, year), or None.
    Returns the full payload dict: {driver_name, constructor, final_position, final_points, races}.
    """
    normalized_code = str(driver_code).upper()
    record = DriverSeasonBreakdown.objects.filter(
        driver_code=normalized_code, year=int(year)
    ).first()
    if record is None:
        return None
    return dict(record.payload or {})
