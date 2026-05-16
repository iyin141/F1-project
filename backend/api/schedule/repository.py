"""Repository layer for schedule data."""
from __future__ import annotations

from api.models import SeasonSchedule


def get_persisted_season_schedule(year: int) -> list[dict] | None:
    """Return the persisted season schedule for a given year, or None."""
    record = SeasonSchedule.objects.filter(year=year).first()
    if record is None:
        return None
    return record.payload.get("races", [])


def get_persisted_race_by_round(year: int, round_number: int) -> dict | None:
    """Return a single race's info from the persisted schedule."""
    record = SeasonSchedule.objects.filter(year=year).first()
    if record is None:
        return None
    for race in record.payload.get("races", []):
        if race.get("round") == round_number:
            return race
    return None
