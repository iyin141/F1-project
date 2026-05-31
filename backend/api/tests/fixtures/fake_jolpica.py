"""Minimal placeholder fixture for fake_jolpica used during diagnostics.

This file provides simple no-op implementations so Django can import
modules that re-export these test fixtures at runtime in development.
Do not use these placeholders in real tests; replace with the canonical
test fixtures under `api.tests.fixtures` when running test suites.
"""
from __future__ import annotations

def fetch_driver_standings(*args, **kwargs):
    return []

def get_season_driver_map(*args, **kwargs):
    return {}

def resolve_driver_id(*args, **kwargs):
    return None

def fetch_all_driver_results(*args, **kwargs):
    return []

def get_all_champions(*args, **kwargs):
    return []

def fetch_season_results(*args, **kwargs):
    return []

def fetch_season_qualifying(*args, **kwargs):
    return []

def fetch_season_sprint(*args, **kwargs):
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
