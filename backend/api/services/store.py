"""
Store functions — write normalised data into JSONB model rows.

Each function accepts parsed data and performs an update_or_create so that
calling it twice with the same key is idempotent.
"""
from __future__ import annotations

from typing import Optional

from django.db import transaction

from api.models import (
    ConstructorStandings,
    DriverLapAnalysis,
    DriverStandings,
    DriverTelemetry,
    PracticeResultData,
    QualifyingResultData,
    RaceResultData,
    SessionData,
)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def store_qualifying_results(year: int, round_number: int, results_list: list[dict]) -> QualifyingResultData:
    """Upsert a QualifyingResultData row for (year, round_number)."""
    record, _ = QualifyingResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        defaults={"payload": {"results": results_list}},
    )
    return record


def store_sprint_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='S')."""
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="S",
        defaults={"payload": {"results": results_list}},
    )
    return record


def store_sprint_shootout_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='SQ')."""
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="SQ",
        defaults={"payload": {"results": results_list}},
    )
    return record


def store_practice_results(
    year: int, round_number: int, session: str, results_list: list[dict]
) -> PracticeResultData:
    """Upsert a PracticeResultData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    record, _ = PracticeResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"results": results_list}},
    )
    return record


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def store_driver_standings(year: int, standings_list: list[dict]) -> DriverStandings:
    """
    Upsert the season-level DriverStandings row (driver_code=None) for a given year.

    The payload schema is: {"standings": [...]}
    Each item in standings_list should have at least: position, driver_name, points, wins, constructor.
    """
    record, _ = DriverStandings.objects.update_or_create(
        year=year,
        driver_code=None,
        defaults={"payload": {"standings": standings_list}},
    )
    return record


def store_constructor_standings(year: int, standings_list: list[dict]) -> ConstructorStandings:
    """
    Upsert the ConstructorStandings row for a given year.

    The payload schema is: {"standings": [...]}
    """
    record, _ = ConstructorStandings.objects.update_or_create(
        year=year,
        defaults={"payload": {"standings": standings_list}},
    )
    return record


# ---------------------------------------------------------------------------
# Unified / session-wide data
# ---------------------------------------------------------------------------

def store_session_data(
    year: int,
    round_number: int,
    session: str,
    data_dict: dict,
) -> SessionData:
    """
    Upsert a SessionData row for (year, round_number, session).

    data_dict should contain any combination of:
        {
            "weather": [...],
            "pit_stops": [...],
            "incidents": [...],
            "positions": [...],
            "drs": [...],
            "track_status": [...],
        }

    Keys present in data_dict are merged into the existing payload so that
    partial updates (e.g. only weather) don't clobber already-stored keys.
    """
    normalized_session = str(session).upper()
    with transaction.atomic():
        record, created = SessionData.objects.select_for_update().get_or_create(
            year=year,
            round_number=round_number,
            session=normalized_session,
            defaults={"payload": {}},
        )
        # Merge: preserve existing keys that aren't being overwritten
        updated_payload = dict(record.payload or {})
        updated_payload.update(data_dict)
        record.payload = updated_payload
        record.save(update_fields=["payload", "updated_at"])
    return record


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def store_driver_telemetry(
    year: int,
    round_number: int,
    session: str,
    driver_code: str,
    lap: int,
    telemetry_points: list[dict],
    summary: Optional[dict] = None,
) -> DriverTelemetry:
    """
    Upsert a DriverTelemetry row for (year, round_number, session, driver_code, lap).

    payload schema:
        {
            "driver_code": str,
            "lap": int,
            "points": [...telemetry rows...],
            "summary": {...optional stats...},
        }
    """
    normalized_session = str(session).upper()
    normalized_driver = str(driver_code).upper()
    payload = {
        "driver_code": normalized_driver,
        "lap": int(lap),
        "points": telemetry_points,
        "summary": summary or {},
    }
    record, _ = DriverTelemetry.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver_code=normalized_driver,
        lap=int(lap),
        defaults={"payload": payload},
    )
    return record
