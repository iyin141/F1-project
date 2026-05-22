"""Minimal fake FastF1 implementation used during unit tests to avoid network calls.

This provides the small subset of the FastF1 API the codebase relies on:
- `get_session(year, round_or_event, session_type)` -> returns a FakeSession
- `get_event_schedule(year)` -> returns an empty DataFrame by default

Tests that require richer behavior should patch `api.services.analysis.fastf1.get_session`
or `api.services.unified_service.fastf1` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd
from datetime import datetime


@dataclass
class FakeSession:
    """A minimal session-like object exposing empty datasets."""
    laps: pd.DataFrame | None = None
    weather: pd.DataFrame | None = None
    messages: pd.DataFrame | None = None
    track_status: pd.DataFrame | None = None
    date: datetime | None = None
    _loaded_flags: dict | None = None

    def __post_init__(self):
        # Provide empty DataFrames with expected shapes
        empty = pd.DataFrame()
        self.laps = self.laps if self.laps is not None else empty
        self.weather = self.weather if self.weather is not None else empty
        self.messages = self.messages if self.messages is not None else empty
        self.track_status = self.track_status if self.track_status is not None else empty
        self._loaded_flags = self._loaded_flags or {}

    def load(self, **kwargs) -> None:
        # No-op for tests; respects kwargs but does nothing
        return None

    # Provide a convenience used by some callers: attribute access for datasets
    def __getattr__(self, name: str) -> Any:
        if name in ("laps", "weather", "messages", "track_status"):
            return getattr(self, name)
        raise AttributeError(name)


def get_session(year: int, round_or_event: Any, session_type: str) -> FakeSession:
    """Return a basic FakeSession. Tests may patch this function for richer behavior."""
    return FakeSession()


def get_event_schedule(year: int) -> pd.DataFrame:
    """Return an empty schedule DataFrame by default.

    Tests that need a populated schedule should patch this function.
    """
    return pd.DataFrame(columns=["RoundNumber", "EventName"]) 


__all__ = ["get_session", "get_event_schedule"]
