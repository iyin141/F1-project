"""Backward-compatibility shim for the fake Jolpica client.

The true test fixture has been moved to `api.tests.fixtures.fake_jolpica`.
This module keeps the old import path working so existing code does not
need to change. Tests should import the fixture directly from
`api.tests.fixtures` when they need to patch it.
"""
from __future__ import annotations

# Re-export everything from the test fixtures package to preserve the
# historical import path `api.drivers.fake_jolpica`.
from api.tests.fixtures.fake_jolpica import *  # type: ignore

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
