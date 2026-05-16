"""
Backward-compatibility shim for schedule service.
Redirects to the new api.schedule.services module.
"""
from api.schedule.services import get_season_schedule, get_race_by_round  # noqa: F401
