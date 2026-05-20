"""Driver standings service — fetches full grid standings for a year."""
from __future__ import annotations

import logging
import time

from api.common.readiness import build_readiness
from api.common.utils import is_current_year
from api.common.request_id import get_request_id
from api.queue.manager import TaskManager
from api.tasks import populate_standings

from api.drivers.repository import get_persisted_driver_standings
from api.drivers.jolpica_client import fetch_driver_standings

logger = logging.getLogger(__name__)


def get_driver_standings(year: int) -> dict:
    """Fetch the F1 driver standings for a given year. DB-first strategy."""
    if year is None:
        raise ValueError("year is required")

    extract_start = time.time()
    logger.info(
        "event=data_extract_start",
        extra={
            "request_id": get_request_id(),
            "endpoint": "driver_standings",
            "year": year,
        },
    )

    persisted = get_persisted_driver_standings(year)
    if persisted is not None:
        duration_ms = (time.time() - extract_start) * 1000
        logger.info(
            "event=data_extract_complete",
            extra={
                "request_id": get_request_id(),
                "endpoint": "driver_standings",
                "rows": len(persisted),
                "duration_ms": f"{duration_ms:.1f}",
                "source": "cache",
            },
        )
        return {
            "meta": {
                "year": int(year),
                "row_count": len(persisted),
                "readiness": build_readiness(True, ["driver_standings_persisted"], []),
            },
            "data": persisted,
        }

    data = fetch_driver_standings(year)

    if data is None:
        duration_ms = (time.time() - extract_start) * 1000
        logger.info(
            "event=data_extract_complete",
            extra={
                "request_id": get_request_id(),
                "endpoint": "driver_standings",
                "rows": 0,
                "duration_ms": f"{duration_ms:.1f}",
                "source": "api_failed",
            },
        )
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": build_readiness(
                    False, [], ["driver_standings_api"],
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
                    False, [], ["driver_standings_api"],
                    f"No driver standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    driver_standings = standings_list[0].get("DriverStandings", [])

    rows = [
        {
            "position": int(d.get("position", 0)),
            "driver_name": f"{d['Driver'].get('givenName', '')} {d['Driver'].get('familyName', '')}".strip(),
            "points": float(d.get("points", 0)),
            "wins": int(d.get("wins", 0)),
            "constructor": d.get("Constructors", [{}])[0].get("name", ""),
        }
        for d in driver_standings
    ]

    if not rows:
        return {
            "meta": {
                "year": int(year),
                "row_count": 0,
                "readiness": build_readiness(
                    False, [], ["driver_standings_api"],
                    f"No driver standings data returned for {year}.",
                ),
            },
            "data": [],
        }

    logger.info("event=api_live_fetch_success source=driver_standings year=%s row_count=%s", year, len(rows))
    if not is_current_year(year):
        TaskManager.enqueue_if_needed(
            task_key=f"standings:{int(year)}",
            task_fn=populate_standings,
            year=int(year),
        )

    return {
        "meta": {
            "year": int(year),
            "row_count": len(rows),
            "readiness": build_readiness(True, ["driver_standings_api"], []),
        },
        "data": rows,
    }
