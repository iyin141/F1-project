"""Repository layer for results data."""
from __future__ import annotations

from api.models import RaceResultData, QualifyingResultData, PracticeResultData


def get_persisted_practice_results(year: int, round_number: int, session: str) -> list[dict] | None:
    """Return the persisted practice results for a given year, round, and session."""
    record = PracticeResultData.objects.filter(year=year, round_number=round_number, session=session).first()
    if record is None:
        return None
    return record.payload.get("data", [])


def get_persisted_qualifying_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted qualifying results."""
    record = QualifyingResultData.objects.filter(year=year, round_number=round_number).first()
    if record is None:
        return None
    return record.payload.get("data", [])


def get_persisted_race_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted race results."""
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="R").first()
    if record is None:
        return None
    return record.payload.get("data", [])


def get_persisted_sprint_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted sprint results."""
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="S").first()
    if record is None:
        return None
    return record.payload.get("data", [])


def get_persisted_sprint_shootout_results(year: int, round_number: int) -> list[dict] | None:
    """Return the persisted sprint shootout results."""
    record = RaceResultData.objects.filter(year=year, round_number=round_number, session="SQ").first()
    if record is None:
        return None
    return record.payload.get("data", [])
