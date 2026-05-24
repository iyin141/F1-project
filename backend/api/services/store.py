"""
Store functions — write normalised data into JSONB model rows.

Each function accepts parsed data and performs an update_or_create so that
calling it twice with the same key is idempotent. Also backfills Redis cache.
"""
from __future__ import annotations

import json
from typing import Optional

from django.db import transaction

from api.models import (
    ConstructorStandings,
    DriverCareer,
    DriverLapAnalysis,
    DriverSeasonBreakdown,
    DriverStandings,
    DriverTelemetry,
    PracticeResultData,
    QualifyingResultData,
    RaceResultData,
    SeasonSchedule,
    SessionData,
)
from api.services.cache import build_cache_key, ttl_for, set_in_cache



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
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, round_number, "Q", "qualifying")
    ttl = ttl_for("qualifying", year)
    set_in_cache(cache_key, json.dumps(results_list), ttl)
    
    return record


def store_sprint_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='S')."""
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="S",
        defaults={"payload": {"results": results_list}},
    )
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, round_number, "S", "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(results_list), ttl)
    
    return record


def store_sprint_shootout_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='SQ')."""
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="SQ",
        defaults={"payload": {"results": results_list}},
    )
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, round_number, "SQ", "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(results_list), ttl)
    
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
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, round_number, normalized_session, "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(results_list), ttl)
    
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
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, 0, "standings", "standings")
    ttl = ttl_for("standings", year)
    set_in_cache(cache_key, json.dumps(standings_list), ttl)
    
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
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, 0, "standings", "constructor_standings")
    ttl = ttl_for("standings", year)
    set_in_cache(cache_key, json.dumps(standings_list), ttl)
    
    return record


# ---------------------------------------------------------------------------
# Season Schedule
# ---------------------------------------------------------------------------

def store_season_schedule(year: int, races_list: list[dict]) -> SeasonSchedule:
    """
    Upsert the SeasonSchedule row for a given year.

    The payload schema is: {"races": [...]}
    Each item should contain at minimum: round, name, date, location, country.
    """
    record, _ = SeasonSchedule.objects.update_or_create(
        year=year,
        defaults={"payload": {"races": races_list}},
    )
    
    # Backfill Redis cache
    cache_key = build_cache_key(year, 0, "schedule", "schedule")
    ttl = ttl_for("schedule", year)
    set_in_cache(cache_key, json.dumps(races_list), ttl)
    
    return record


# ---------------------------------------------------------------------------
# Driver Career & Season Breakdown
# ---------------------------------------------------------------------------

def store_driver_career(
    driver_code: str,
    driver_name: Optional[str],
    nationality: Optional[str],
    career_seasons: list[dict],
    career_totals: dict,
) -> DriverCareer:
    """
    Upsert the DriverCareer row for a driver.

    Natural key: driver_code (unique column).
    Payload schema:
        {
            "driver_name": str | None,
            "nationality": str | None,
            "career": [...],
            "career_totals": {...},
        }
    """
    normalized_code = str(driver_code).upper()
    payload = {
        "driver_name": driver_name,
        "nationality": nationality,
        "career": career_seasons,
        "career_totals": career_totals,
    }
    record, _ = DriverCareer.objects.update_or_create(
        driver_code=normalized_code,
        defaults={"payload": payload},
    )
    
    # Backfill Redis cache
    cache_key = f"f1:career:{normalized_code}"
    ttl = ttl_for("career", 2020)  # Career data is historical (7 days per cache.py logic)
    set_in_cache(cache_key, json.dumps(payload), ttl)
    
    return record


def store_driver_season_breakdown(
    driver_code: str,
    year: int,
    driver_name: Optional[str],
    constructor: Optional[str],
    final_position: Optional[int],
    final_points: Optional[float],
    races: list[dict],
) -> DriverSeasonBreakdown:
    """
    Upsert the DriverSeasonBreakdown row for (driver_code, year).

    Natural key: (driver_code, year) — both are NOT NULL, DB constraint enforced.
    Payload schema:
        {
            "driver_name": str | None,
            "constructor": str | None,
            "final_position": int | None,
            "final_points": float | None,
            "races": [...],
        }
    """
    normalized_code = str(driver_code).upper()
    payload = {
        "driver_name": driver_name,
        "constructor": constructor,
        "final_position": final_position,
        "final_points": final_points,
        "races": races,
    }
    record, _ = DriverSeasonBreakdown.objects.update_or_create(
        driver_code=normalized_code,
        year=int(year),
        defaults={"payload": payload},
    )
    
    # Backfill Redis cache
    cache_key = f"f1:season:{normalized_code}:{year}"
    ttl = ttl_for("results", year)  # Use results TTL since it's season data
    set_in_cache(cache_key, json.dumps(payload), ttl)
    
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
    laps_payload: dict,
) -> DriverTelemetry:
    """
    Upsert a DriverTelemetry row for (year, round_number, session, driver_code).

    laps_payload keys are string lap numbers: {"1": {field: [values]}, "2": {...}}.
    The `lap` column is set to None — it is retained for schema compatibility only.

    Payload fields per lap:
        distance, speed, throttle, brake, gear, rpm, drs, relative_distance
    """
    record, _ = DriverTelemetry.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=str(session).upper(),
        driver_code=str(driver_code).upper(),
        defaults={"payload": laps_payload, "lap": None},
    )
    return record
