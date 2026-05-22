"""Backward compatibility shim for results service."""
import warnings

warnings.warn(
    "api.services.results is deprecated. Import from api.results.services instead.",
    DeprecationWarning,
    stacklevel=2,
)

from api.results.services.race import get_race_results
from api.results.services.qualifying import get_qualifying_results
from api.results.services.sprint import get_sprint_results, get_sprint_shootout_results
from api.results.services.practice import get_practice_session_results
from api.results.repository import get_persisted_race_results
# Expose fastf1 runtime for backwards-compatible test patching (tests patch api.services.results.fastf1.get_session)
from api.services.unified_service import fastf1

__all__ = [
    "get_race_results",
    "get_qualifying_results",
    "get_sprint_results",
    "get_sprint_shootout_results",
    "get_practice_session_results",
    "get_persisted_race_results",
    "fastf1",
]
