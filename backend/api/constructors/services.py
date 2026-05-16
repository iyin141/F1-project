"""
Constructor standings service — business logic layer.

Call chain: view → service → repository (DB) or jolpica_client (API).
"""
from __future__ import annotations

import logging

from api.common.readiness import build_readiness
from api.common.utils import is_current_year
from api.queue.manager import TaskManager
from api.tasks import populate_constructor_standings

from api.constructors.repository import get_persisted_constructor_standings
from api.constructors.jolpica_client import fetch_constructor_standings

logger = logging.getLogger(__name__)


def get_constructor_standings(year: int) -> dict:
    """
    Fetch the F1 constructor standings for a given year.

    Strategy: DB-first, then Jolpica API fallback with async persistence.
    """
    if year is None:
        raise ValueError("year is required")

    # 1. Try persisted data first
    persisted = get_persisted_constructor_standings(year)
    if persisted is not None:
        return {
            "meta": {
                "year": int(year),
                "row_count": len(persisted),
                "readiness": build_readiness(True, ["constructor_standings_persisted"], []),
            },
            "data": persisted,
        }

    # 2. Fetch from external API
    data = fetch_constructor_standings(year)

    if data is None:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": build_readiness(
                    False, [], ["constructor_standings_api"],
                    "Standings API unavailable",
                ),
            },
            "data": [],
        }

    standings_list = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")

    if not standings_list:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": build_readiness(
                    False, [], ["constructor_standings_api"],
                    f"No constructor standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    constructor_standings = standings_list[0].get("ConstructorStandings", [])

    rows = [
        {
            "position": int(c.get("position", 0)),
            "constructor_name": c.get("Constructor", {}).get("name", ""),
            "points": float(c.get("points", 0)),
            "wins": int(c.get("wins", 0)),
        }
        for c in constructor_standings
    ]

    if not rows:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": build_readiness(
                    False, [], ["constructor_standings_api"],
                    f"No constructor standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    # 3. Enqueue background persistence for historical years
    logger.info("event=api_live_fetch_success source=constructor_standings year=%s row_count=%s", year, len(rows))
    if not is_current_year(year):
        TaskManager.enqueue_if_needed(
            task_key=f"constructor_standings:{int(year)}",
            task_fn=populate_constructor_standings,
            year=int(year),
        )

    return {
        "meta": {
            "year": int(year),
            "row_count": len(rows),
            "readiness": build_readiness(True, ["constructor_standings_api"], []),
        },
        "data": rows,
    }
