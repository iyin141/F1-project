from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache

from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverStandings
from api.drivers.jolpica_client import fetch_driver_standings
from api.common.readiness import build_readiness
import traceback

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_standings(self, task_key: str, year: int):
    """
    Populate DriverStandings for a season year.
    Task key: standings:{year}
    
    Publishes full serialized standings payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_standings task_key=%s year=%s", task_key, year)
    canonical_task_key = f"standings:{int(year)}"
    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(status="running", started_at=timezone.now())

    try:
        data = fetch_driver_standings(year)
        rows = []
        if data:
            standings_list = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")
            if standings_list:
                driver_standings = standings_list[0].get("DriverStandings", [])
                for d in driver_standings:
                    rows.append({
                        "position": int(d.get("position", 0)),
                        "driver_name": f"{d['Driver'].get('givenName', '')} {d['Driver'].get('familyName', '')}".strip(),
                        "points": float(d.get("points", 0)),
                        "wins": int(d.get("wins", 0)),
                        "constructor": d.get("Constructors", [{}])[0].get("name", ""),
                    })

        readiness = build_readiness(
            bool(rows),
            ["driver_standings_api"] if rows else [],
            [] if rows else ["driver_standings_api"],
            None if rows else f"No driver standings data returned for {year}.",
            [] if rows else [f"No driver standings data returned for {year}."]
        )

        serialized_data = {
            "year": year,
            "drivers": rows,
            "readiness": readiness
        }

        cache_key = f"driver_standings:{year}"
        
        # Publish and cache
        worker_utils.handle_result(
            task_key=canonical_task_key,
            data_type="driver_standings",
            serialized_data=serialized_data,
            cache_key=cache_key,
            year=year,
        )

        # Asynchronous DB Save
        if rows:
            DriverStandings.objects.update_or_create(
                year=int(year),
                driver_code=None,
                defaults={"payload": {"standings": rows}}
            )

        logger.info(
            "event=celery_success task=populate_standings task_key=%s year=%s standings=%d",
            task_key, year, len(rows),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_standings task_key=%s year=%s", task_key, year)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
        cache.delete(f"task_lock:{canonical_task_key}")
