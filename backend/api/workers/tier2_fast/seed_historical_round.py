from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.models import TaskRecord
from api.services.task_manager import TaskManager
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="backfill", rate_limit="3/m")
def seed_historical_round(self, task_key: str, year: int, round_number: int, data_types: list):
    """
    Seed a single historical round for the given data_types.

    Dispatches sub-tasks (populate_race_results and specific unified workers) for
    each requested type so that backfill can be interrupted and resumed without
    losing partial progress.

    Task key: seed_round:{year}:{round}
    Phase 6: Dispatched by seed_historical management command / seeding service.
    """
    logger.info(
        "event=celery_start task=seed_historical_round task_key=%s year=%s round=%s types=%s",
        task_key, year, round_number, data_types,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.tasks import _SEED_SESSION_MAP

        for dtype in data_types:
            session_type = _SEED_SESSION_MAP.get(dtype)
            if session_type:
                sub_key = f"race_results:{int(year)}:{int(round_number)}:{session_type}"
                # import target task dynamically to avoid import cycles
                from api.workers.tier2_fast.populate_race_results import populate_race_results

                TaskManager.enqueue_if_needed(
                    sub_key,
                    populate_race_results,
                    int(year),
                    int(round_number),
                    session_type,
                )
            elif dtype == "session_data":
                # Dispatch all 6 unified workers for session_data
                sub_types = ["weather", "pit_stops", "incidents", "positions", "drs", "track_status"]
                worker_map = {
                    "weather": "populate_weather",
                    "pit_stops": "populate_pit_stops",
                    "incidents": "populate_incidents",
                    "positions": "populate_positions",
                    "drs": "populate_drs",
                    "track_status": "populate_track_status",
                }
                for sub_type in sub_types:
                    sub_key = f"{sub_type}:{int(year)}:{int(round_number)}:R"
                    # Import specific worker
                    if sub_type == "weather":
                        from api.workers.tier2_fast.populate_weather import populate_weather
                        TaskManager.enqueue_if_needed(sub_key, populate_weather, int(year), int(round_number), "R")
                    elif sub_type == "pit_stops":
                        from api.workers.tier2_fast.populate_pit_stops import populate_pit_stops
                        TaskManager.enqueue_if_needed(sub_key, populate_pit_stops, int(year), int(round_number), "R")
                    elif sub_type == "incidents":
                        from api.workers.tier2_fast.populate_incidents import populate_incidents
                        TaskManager.enqueue_if_needed(sub_key, populate_incidents, int(year), int(round_number), "R")
                    elif sub_type == "positions":
                        from api.workers.tier3_medium.populate_positions import populate_positions
                        TaskManager.enqueue_if_needed(sub_key, populate_positions, int(year), int(round_number), "R")
                    elif sub_type == "drs":
                        from api.workers.tier3_medium.populate_drs import populate_drs
                        TaskManager.enqueue_if_needed(sub_key, populate_drs, int(year), int(round_number), "R")
                    elif sub_type == "track_status":
                        from api.workers.tier3_medium.populate_track_status import populate_track_status
                        TaskManager.enqueue_if_needed(sub_key, populate_track_status, int(year), int(round_number), "R")

        pubsub.publish_result(task_key, {"source": "worker"})
        TaskRecord.objects.filter(task_key=task_key).update(status="complete", completed_at=timezone.now())
        logger.info(
            "event=celery_success task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
