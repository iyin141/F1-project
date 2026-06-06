from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache

from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, ConstructorStandings
from api.constructors.jolpica_client import fetch_constructor_standings
from api.common.readiness import build_readiness
import traceback

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_constructor_standings(self, task_key: str, year: int):
    """
    Populate ConstructorStandings for a season year.
    Task key: constructor_standings:{year}
    
    Publishes full serialized standings payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_constructor_standings task_key=%s year=%s", task_key, year)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        data = fetch_constructor_standings(year)
        rows = []
        if data:
            standings_list = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")
            if standings_list:
                constructor_standings = standings_list[0].get("ConstructorStandings", [])
                for c in constructor_standings:
                    rows.append({
                        "position": int(c.get("position", 0)),
                        "constructor_name": c.get("Constructor", {}).get("name", ""),
                        "points": float(c.get("points", 0)),
                        "wins": int(c.get("wins", 0)),
                    })

        readiness = build_readiness(
            bool(rows),
            ["constructor_standings_api"] if rows else [],
            [] if rows else ["constructor_standings_api"],
            None if rows else f"No constructor standings data returned for {year}.",
            [] if rows else [f"No constructor standings data returned for {year}."]
        )

        serialized_data = {
            "year": year,
            "constructors": rows,
            "readiness": readiness
        }

        cache_key = f"constructor_standings:{year}"
        
        # Publish and cache
        worker_utils.handle_result(
            task_key=task_key,
            data_type="constructor_standings",
            serialized_data=serialized_data,
            cache_key=cache_key,
            year=year,
        )

        # Asynchronous DB Save
        if rows:
            ConstructorStandings.objects.update_or_create(
                year=int(year),
                defaults={"payload": {"standings": rows}}
            )

        logger.info(
            "event=celery_success task=populate_constructor_standings task_key=%s year=%s standings=%d",
            task_key, year, len(rows),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_constructor_standings task_key=%s year=%s", task_key, year)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
