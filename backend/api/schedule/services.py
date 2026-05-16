"""Service layer for schedule domain."""
from __future__ import annotations

import logging
from datetime import datetime

from api.common.utils import is_current_year
from api.queue.manager import TaskManager
from api.schedule.repository import get_persisted_season_schedule, get_persisted_race_by_round
from api.schedule.fastf1_client import fetch_season_schedule

logger = logging.getLogger(__name__)


def get_season_schedule(year: int | None = None) -> list[dict]:
    """Fetch the F1 season schedule for a given year."""
    if year is None:
        year = datetime.now().year

    persisted_schedule = get_persisted_season_schedule(year)

    try:
        schedule_data = fetch_season_schedule(year)

        # Merge with persisted schedule if available (for robustness)
        if persisted_schedule:
            persisted_by_round = {race["round"]: race for race in persisted_schedule}
            schedule_data = [persisted_by_round.get(race["round"], race) for race in schedule_data]

        if schedule_data and not is_current_year(year):
            from api.tasks import populate_schedule
            TaskManager.enqueue_if_needed(
                task_key=f"schedule:{int(year)}",
                task_fn=populate_schedule,
                year=int(year),
            )

        return schedule_data

    except Exception as e:
        if persisted_schedule:
            return persisted_schedule
        raise Exception(f"Error fetching F1 schedule: {str(e)}")


def get_race_by_round(year: int | None = None, round_number: int | None = None) -> dict | None:
    """Get a specific race by round number."""
    if year is None:
        year = datetime.now().year

    persisted_race = get_persisted_race_by_round(year, round_number)
    if persisted_race is not None:
        return persisted_race

    schedule = get_season_schedule(year)

    for race in schedule:
        if race['round'] == round_number:
            return race

    return None
