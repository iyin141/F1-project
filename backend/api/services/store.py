"""
Store functions — write normalised data into JSONB model rows.

Each function accepts parsed data and performs an update_or_create so that
calling it twice with the same key is idempotent. Also backfills Redis cache.
"""
from __future__ import annotations

import json
from typing import Optional

from django.db import transaction
from django.utils import timezone

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
    WeatherData,
    PitStopData,
    IncidentData,
    PositionData,
    DRSData,
    TrackStatusData,
)
from api.services.cache import build_cache_key, ttl_for, set_in_cache
from api.results.serializers import (
    QualifyingResultSerializer,
    RaceResultSerializer,
    PracticeResultSerializer,
)
from api.results.serializers import (
    SprintResultSerializer,
    SprintShootoutResultSerializer,
)
from api.serializers import (
    LapAnalysisRowSerializer,
    StintAnalysisRowSerializer,
    TyreStrategyRowSerializer,
    DriverStandingSerializer,
    ConstructorSerializer,
    RaceSerializer,
    WeatherRowSerializer,
    PitStopRowSerializer,
    IncidentRowSerializer,
    PositionChangeRowSerializer,
    DRSRowSerializer,
    TrackStatusRowSerializer,
)



# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def store_qualifying_results(year: int, round_number: int, results_list: list[dict]) -> QualifyingResultData:
    """Upsert a QualifyingResultData row for (year, round_number)."""
    # Serialize into canonical schema and persist under `payload.data`
    serialized = QualifyingResultSerializer(results_list, many=True).data
    # Persist both the canonical `data` and legacy `results` key for
    # backwards compatibility with tools/tests expecting `payload["results"]`.
    record, _ = QualifyingResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        defaults={"payload": {"data": serialized, "results": results_list}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, "Q", "qualifying")
    ttl = ttl_for("qualifying", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_sprint_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='S')."""
    serialized = SprintResultSerializer(results_list, many=True).data
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="S",
        defaults={"payload": {"data": serialized, "results": results_list}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, "S", "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_sprint_shootout_results(year: int, round_number: int, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session='SQ')."""
    serialized = SprintShootoutResultSerializer(results_list, many=True).data
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="SQ",
        defaults={"payload": {"data": serialized, "results": results_list}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, "SQ", "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_practice_results(
    year: int, round_number: int, session: str, results_list: list[dict]
) -> PracticeResultData:
    """Upsert a PracticeResultData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = PracticeResultSerializer(results_list, many=True).data
    record, _ = PracticeResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized, "results": results_list}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_race_results(year: int, round_number: int, session: str, results_list: list[dict]) -> RaceResultData:
    """Upsert a RaceResultData row for (year, round_number, session).

    This general helper covers full race (`R`) writes as well as other race-session
    types if callers prefer a single entrypoint.
    """
    normalized_session = str(session).upper()
    serialized = RaceResultSerializer(results_list, many=True).data
    record, _ = RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized, "results": results_list}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "results")
    ttl = ttl_for("results", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

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
    serialized = DriverStandingSerializer(standings_list, many=True).data
    record, _ = DriverStandings.objects.update_or_create(
        year=year,
        driver_code=None,
        defaults={"payload": {"standings": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, 0, "standings", "standings")
    ttl = ttl_for("standings", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_constructor_standings(year: int, standings_list: list[dict]) -> ConstructorStandings:
    """
    Upsert the ConstructorStandings row for a given year.

    The payload schema is: {"standings": [...]}
    """
    serialized = ConstructorSerializer(standings_list, many=True).data
    record, _ = ConstructorStandings.objects.update_or_create(
        year=year,
        defaults={"payload": {"standings": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, 0, "standings", "constructor_standings")
    ttl = ttl_for("standings", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

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
    serialized = RaceSerializer(races_list, many=True).data
    record, _ = SeasonSchedule.objects.update_or_create(
        year=year,
        defaults={"payload": {"races": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, 0, "schedule", "schedule")
    ttl = ttl_for("schedule", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

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

def store_weather_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> WeatherData:
    """Upsert a WeatherData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = WeatherRowSerializer(rows_list, many=True).data
    record, _ = WeatherData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "weather")
    ttl = ttl_for("weather", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_pit_stop_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> PitStopData:
    """Upsert a PitStopData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = PitStopRowSerializer(rows_list, many=True).data
    record, _ = PitStopData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "pit_stops")
    ttl = ttl_for("pit_stops", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_incident_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> IncidentData:
    """Upsert an IncidentData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = IncidentRowSerializer(rows_list, many=True).data
    record, _ = IncidentData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "incidents")
    ttl = ttl_for("incidents", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_position_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> PositionData:
    """Upsert a PositionData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = PositionChangeRowSerializer(rows_list, many=True).data
    record, _ = PositionData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "positions")
    ttl = ttl_for("positions", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_drs_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> DRSData:
    """Upsert a DRSData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = DRSRowSerializer(rows_list, many=True).data
    record, _ = DRSData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "drs")
    ttl = ttl_for("drs", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

    return record


def store_track_status_data(
    year: int,
    round_number: int,
    session: str,
    rows_list: list[dict],
) -> TrackStatusData:
    """Upsert a TrackStatusData row for (year, round_number, session)."""
    normalized_session = str(session).upper()
    serialized = TrackStatusRowSerializer(rows_list, many=True).data
    record, _ = TrackStatusData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        defaults={"payload": {"data": serialized}},
    )

    # Backfill Redis cache with canonical JSON
    cache_key = build_cache_key(year, round_number, normalized_session, "track_status")
    ttl = ttl_for("track_status", year)
    set_in_cache(cache_key, json.dumps(serialized), ttl)

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


def store_driver_lap_analysis(
    year: int,
    round_number: int,
    session: str,
    driver_code: str,
    laps: list[dict] | None = None,
    stints: list[dict] | None = None,
    tyre_strategy: list[dict] | None = None,
    pace: dict | None = None,
    sectors: dict | None = None,
) -> DriverLapAnalysis:
    """Upsert a DriverLapAnalysis row for a single driver and normalise rows.

    Ensures each lap/stint/tyre row includes `driver_code` and required defaults
    so downstream serializers don't KeyError on missing keys.
    """
    normalized_session = str(session).upper()
    dc = str(driver_code).upper()

    # Normalise laps
    norm_laps = []
    for lap in (laps or []):
        l = dict(lap)
        l.setdefault("driver_code", dc)
        l.setdefault("lap_number", l.get("lap_number"))
        l.setdefault("lap_time", l.get("lap_time"))
        l.setdefault("sector1", l.get("sector1") or None)
        l.setdefault("sector2", l.get("sector2") or None)
        l.setdefault("sector3", l.get("sector3") or None)
        l.setdefault("compound", l.get("compound") or None)
        l.setdefault("stint", l.get("stint"))
        l.setdefault("is_personal_best", bool(l.get("is_personal_best", False)))
        norm_laps.append(l)

    # Normalise stints
    norm_stints = []
    for s in (stints or []):
        ss = dict(s)
        ss.setdefault("driver_code", dc)
        ss.setdefault("driver_number", ss.get("driver_number"))
        ss.setdefault("stint_number", ss.get("stint_number") or ss.get("stint"))
        ss.setdefault("compound", ss.get("compound") or None)
        ss.setdefault("lap_start", ss.get("lap_start"))
        ss.setdefault("lap_end", ss.get("lap_end"))
        if ss.get("total_laps") is None:
            try:
                ls = int(ss.get("lap_start")) if ss.get("lap_start") is not None else None
                le = int(ss.get("lap_end")) if ss.get("lap_end") is not None else None
                ss["total_laps"] = (le - ls + 1) if (ls and le) else 0
            except Exception:
                ss["total_laps"] = 0
        norm_stints.append(ss)

    # Normalise tyre strategy rows
    norm_tyre = []
    for t in (tyre_strategy or []):
        tt = dict(t)
        tt.setdefault("driver_code", dc)
        tt.setdefault("driver_number", tt.get("driver_number"))
        tt.setdefault("stint_number", tt.get("stint_number") or tt.get("stint"))
        tt.setdefault("compound", tt.get("compound") or None)
        tt.setdefault("lap_start", tt.get("lap_start"))
        tt.setdefault("lap_end", tt.get("lap_end"))
        if tt.get("laps_in_stint") is None:
            try:
                ls = int(tt.get("lap_start")) if tt.get("lap_start") is not None else None
                le = int(tt.get("lap_end")) if tt.get("lap_end") is not None else None
                tt["laps_in_stint"] = (le - ls + 1) if (ls and le) else 0
            except Exception:
                tt["laps_in_stint"] = 0
        norm_tyre.append(tt)

    # Pace and sectors are dicts — ensure driver_code is present for consistency
    norm_pace = dict(pace or {})
    if norm_pace:
        norm_pace.setdefault("driver_code", dc)

    norm_sectors = dict(sectors or {})
    if norm_sectors:
        norm_sectors.setdefault("driver_code", dc)

    # Validate rows via serializers where it makes sense (laps/stints/tyre)
    serialized_laps = LapAnalysisRowSerializer(norm_laps, many=True).data
    serialized_stints = StintAnalysisRowSerializer(norm_stints, many=True).data
    serialized_tyre = TyreStrategyRowSerializer(norm_tyre, many=True).data

    record, _ = DriverLapAnalysis.objects.update_or_create(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver_code=dc,
        defaults={
            "payload": {
                "laps": serialized_laps,
                "stints": serialized_stints,
                "tyre_strategy": serialized_tyre,
                "pace": norm_pace,
                "sectors": norm_sectors,
            }
        },
    )

    return record


def bulk_store_driver_lap_analysis(
    year: int,
    round_number: int,
    session: str,
    parsed_session: "Any",
) -> None:
    """Bulk upsert DriverLapAnalysis rows for all drivers in a session.
    
    Performs normalization and serialization in memory, then uses a single 
    bulk_create and bulk_update to save all drivers, drastically reducing DB latency.
    """
    normalized_session = str(session).upper()
    all_drivers = parsed_session.all_drivers
    if not all_drivers:
        return

    # 1. Normalize and serialize data for all drivers in memory
    prepared_payloads = {}
    
    for driver_code in all_drivers:
        dc = str(driver_code).upper()
        
        laps = parsed_session.laps_by_driver.get(dc, [])
        stints = parsed_session.stints_by_driver.get(dc, [])
        tyre_strategy = parsed_session.tyre_by_driver.get(dc, [])
        pace = parsed_session.pace_by_driver.get(dc, {})
        sectors = parsed_session.sectors_by_driver.get(dc, {})

        # Normalise laps
        norm_laps = []
        for lap in (laps or []):
            l = dict(lap)
            l.setdefault("driver_code", dc)
            l.setdefault("lap_number", l.get("lap_number"))
            l.setdefault("lap_time", l.get("lap_time"))
            l.setdefault("sector1", l.get("sector1") or None)
            l.setdefault("sector2", l.get("sector2") or None)
            l.setdefault("sector3", l.get("sector3") or None)
            l.setdefault("compound", l.get("compound") or None)
            l.setdefault("stint", l.get("stint"))
            l.setdefault("is_personal_best", bool(l.get("is_personal_best", False)))
            norm_laps.append(l)

        # Normalise stints
        norm_stints = []
        for s in (stints or []):
            ss = dict(s)
            ss.setdefault("driver_code", dc)
            ss.setdefault("driver_number", ss.get("driver_number"))
            ss.setdefault("stint_number", ss.get("stint_number") or ss.get("stint"))
            ss.setdefault("compound", ss.get("compound") or None)
            ss.setdefault("lap_start", ss.get("lap_start"))
            ss.setdefault("lap_end", ss.get("lap_end"))
            if ss.get("total_laps") is None:
                try:
                    ls = int(ss.get("lap_start")) if ss.get("lap_start") is not None else None
                    le = int(ss.get("lap_end")) if ss.get("lap_end") is not None else None
                    ss["total_laps"] = (le - ls + 1) if (ls and le) else 0
                except Exception:
                    ss["total_laps"] = 0
            norm_stints.append(ss)

        # Normalise tyre strategy rows
        norm_tyre = []
        for t in (tyre_strategy or []):
            tt = dict(t)
            tt.setdefault("driver_code", dc)
            tt.setdefault("driver_number", tt.get("driver_number"))
            tt.setdefault("stint_number", tt.get("stint_number") or tt.get("stint"))
            tt.setdefault("compound", tt.get("compound") or None)
            tt.setdefault("lap_start", tt.get("lap_start"))
            tt.setdefault("lap_end", tt.get("lap_end"))
            if tt.get("laps_in_stint") is None:
                try:
                    ls = int(tt.get("lap_start")) if tt.get("lap_start") is not None else None
                    le = int(tt.get("lap_end")) if tt.get("lap_end") is not None else None
                    tt["laps_in_stint"] = (le - ls + 1) if (ls and le) else 0
                except Exception:
                    tt["laps_in_stint"] = 0
            norm_tyre.append(tt)

        # Pace and sectors are dicts
        norm_pace = dict(pace or {})
        if norm_pace:
            norm_pace.setdefault("driver_code", dc)

        norm_sectors = dict(sectors or {})
        if norm_sectors:
            norm_sectors.setdefault("driver_code", dc)

        # Validate rows via serializers where it makes sense
        serialized_laps = LapAnalysisRowSerializer(norm_laps, many=True).data
        serialized_stints = StintAnalysisRowSerializer(norm_stints, many=True).data
        serialized_tyre = TyreStrategyRowSerializer(norm_tyre, many=True).data

        prepared_payloads[dc] = {
            "laps": serialized_laps,
            "stints": serialized_stints,
            "tyre_strategy": serialized_tyre,
            "pace": norm_pace,
            "sectors": norm_sectors,
        }

    # 2. Fetch existing records in a single query
    existing_records_qs = DriverLapAnalysis.objects.filter(
        year=year,
        round_number=round_number,
        session=normalized_session,
        driver_code__in=prepared_payloads.keys()
    )
    existing_records = {record.driver_code: record for record in existing_records_qs}

    # 3. Separate into creates and updates
    to_create = []
    to_update = []
    
    now = timezone.now()

    for dc, payload in prepared_payloads.items():
        if dc in existing_records:
            record = existing_records[dc]
            record.payload = payload
            record.updated_at = now
            to_update.append(record)
        else:
            to_create.append(DriverLapAnalysis(
                year=year,
                round_number=round_number,
                session=normalized_session,
                driver_code=dc,
                payload=payload,
                created_at=now,
                updated_at=now
            ))

    # 4. Perform bulk operations
    if to_create:
        DriverLapAnalysis.objects.bulk_create(to_create, batch_size=50)
        
    if to_update:
        DriverLapAnalysis.objects.bulk_update(to_update, ['payload', 'updated_at'], batch_size=50)
