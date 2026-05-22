"""Fake Jolpica (Ergast) client used in unit tests to avoid network calls.

Provides a tiny subset of the real client's API with deterministic, small
responses suitable for the unit test suite. Tests that require richer data
should patch the functions directly.
"""
from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Minimal driver map for tests
_DRIVER_MAP = {
    "hamilton": {"name": "Lewis Hamilton", "nationality": "British", "code": "HAM"},
    "max_verstappen": {"name": "Max Verstappen", "nationality": "Dutch", "code": "VER"},
}


def fetch_driver_standings(year: int) -> dict | None:
    """Return a minimal standings payload (empty lists by default)."""
    logger.info("[FakeJolpica] fetch_driver_standings(%s)", year)
    return {"MRData": {"StandingsTable": {"StandingsLists": []}}}


def get_season_driver_map(year: int) -> Dict[str, dict]:
    """Return a small driver_id -> info mapping for the given year.

    Kept minimal: tests may patch this function for other shapes.
    """
    logger.info("[FakeJolpica] get_season_driver_map(%s)", year)
    return dict(_DRIVER_MAP)


def resolve_driver_id(driver_code: str, year: int | None = None) -> str | None:
    """Resolve FIA code like 'HAM' to a driverId used by Jolpica (e.g. 'hamilton')."""
    code = (driver_code or "").upper()
    for did, info in _DRIVER_MAP.items():
        if info.get("code") == code:
            return did
    return None


def fetch_all_driver_results(driver_id: str) -> List[dict]:
    logger.info("[FakeJolpica] fetch_all_driver_results(%s)", driver_id)
    return []


def get_all_champions() -> dict:
    logger.info("[FakeJolpica] get_all_champions()")
    # Provide a tiny sample to avoid KeyErrors in callers that inspect champions
    return {2021: "max_verstappen", 2020: "hamilton"}


def fetch_season_results(year: int, driver_id: str) -> list:
    logger.info("[FakeJolpica] fetch_season_results(%s, %s)", year, driver_id)
    return []


def fetch_season_qualifying(year: int, driver_id: str) -> list:
    logger.info("[FakeJolpica] fetch_season_qualifying(%s, %s)", year, driver_id)
    return []


def fetch_season_sprint(year: int, driver_id: str) -> list:
    logger.info("[FakeJolpica] fetch_season_sprint(%s, %s)", year, driver_id)
    return []


__all__ = [
    "fetch_driver_standings",
    "get_season_driver_map",
    "resolve_driver_id",
    "fetch_all_driver_results",
    "get_all_champions",
    "fetch_season_results",
    "fetch_season_qualifying",
    "fetch_season_sprint",
]
