"""
Payload extraction functions.

Each function accepts a JSONB payload dict (from a model's .payload field)
and returns the normalised data slice for the corresponding API endpoint.
These are pure functions — no DB access, no FastF1 calls.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Race / session results
# ---------------------------------------------------------------------------

def extract_race_results(payload: dict) -> list[dict]:
    """Return the results list from a RaceResultData(session='R') payload."""
    return list(payload.get("results", []))


def extract_qualifying_results(payload: dict) -> list[dict]:
    """Return the results list from a QualifyingResultData payload."""
    return list(payload.get("results", []))


def extract_sprint_results(payload: dict) -> list[dict]:
    """Return the results list from a RaceResultData(session='S') payload."""
    return list(payload.get("results", []))


def extract_sprint_shootout_results(payload: dict) -> list[dict]:
    """Return the results list from a RaceResultData(session='SQ') payload."""
    return list(payload.get("results", []))


def extract_practice_results(payload: dict) -> list[dict]:
    """Return the results list from a PracticeResultData payload."""
    return list(payload.get("results", []))


# ---------------------------------------------------------------------------
# Lap analysis (DriverLapAnalysis payload slices)
# ---------------------------------------------------------------------------

def extract_stints(payload: dict) -> list[dict]:
    """Return the stints list from a DriverLapAnalysis payload."""
    return list(payload.get("stints", []))


def extract_tyre_strategy(payload: dict) -> list[dict]:
    """Return the tyre_strategy list from a DriverLapAnalysis payload."""
    return list(payload.get("tyre_strategy", []))


def extract_pace(payload: dict) -> Optional[dict]:
    """Return the pace dict from a DriverLapAnalysis payload. None if absent."""
    return payload.get("pace") or None


def extract_sectors(payload: dict) -> Optional[dict]:
    """Return the sectors dict from a DriverLapAnalysis payload. None if absent."""
    return payload.get("sectors") or None


# ---------------------------------------------------------------------------
# Unified / session-wide data (SessionData payload slices)
# ---------------------------------------------------------------------------

def extract_weather(payload: dict) -> list[dict]:
    """Return the weather time-series from a SessionData payload."""
    return list(payload.get("weather", []))


def extract_pit_stops(payload: dict) -> list[dict]:
    """Return the pit stops list from a SessionData payload."""
    return list(payload.get("pit_stops", []))


def extract_incidents(payload: dict) -> list[dict]:
    """Return the incidents list from a SessionData payload."""
    return list(payload.get("incidents", []))


def extract_positions(payload: dict) -> list[dict]:
    """Return the positions list from a SessionData payload."""
    return list(payload.get("positions", []))


def extract_drs(payload: dict) -> list[dict]:
    """Return the DRS activation list from a SessionData payload."""
    return list(payload.get("drs", []))


def extract_track_status(payload: dict) -> list[dict]:
    """Return the track status list from a SessionData payload."""
    return list(payload.get("track_status", []))


# ---------------------------------------------------------------------------
# Telemetry (DriverTelemetry payload)
# ---------------------------------------------------------------------------

def extract_telemetry(payload: dict) -> list[dict]:
    """Return raw telemetry point rows from a DriverTelemetry payload."""
    return list(payload.get("points", []))


def extract_telemetry_summary(payload: dict) -> dict:
    """Return pre-computed summary stats from a DriverTelemetry payload."""
    return dict(payload.get("summary", {}))


def extract_telemetry_overlay(payload_a: dict, payload_b: dict) -> dict:
    """
    Merge two DriverTelemetry payloads for a side-by-side comparison.

    Returns:
        {
            "driver_a": {"driver_code": str, "lap": int, "points": [...]},
            "driver_b": {"driver_code": str, "lap": int, "points": [...]},
        }
    """
    return {
        "driver_a": {
            "driver_code": payload_a.get("driver_code"),
            "lap": payload_a.get("lap"),
            "points": list(payload_a.get("points", [])),
        },
        "driver_b": {
            "driver_code": payload_b.get("driver_code"),
            "lap": payload_b.get("lap"),
            "points": list(payload_b.get("points", [])),
        },
    }


# ---------------------------------------------------------------------------
# Driver standings (DriverStandings payload)
# ---------------------------------------------------------------------------

def extract_driver_standings(payload: dict) -> list[dict]:
    """Return the standings list from a DriverStandings(year=Y, driver_code=None) payload."""
    return list(payload.get("standings", []))
