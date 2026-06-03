from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.models import TaskRecord
from api.services.task_manager import TaskManager
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def prefetch_race_weekend(self, task_key: str, year: int, round_number: int):
    """
    Prefetch core data for a newly-completed race weekend.

    Loads race results, qualifying, and race session data (weather, incidents,
    pit stops).  Does NOT prefetch telemetry, positions, or DRS — those are
    expensive and should only be loaded on demand.

    Task key: prefetch:{year}:{round}
    Phase 6: Fired by check_for_completed_sessions beat task.
    """
    logger.info(
        "event=celery_start task=prefetch_race_weekend task_key=%s year=%s round=%s",
        task_key, year, round_number,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        # Race results + qualifying results
        for session_type, prefix in [("R", "race_results"), ("Q", "qualifying")]:
            sub_key = f"{prefix}:{int(year)}:{int(round_number)}"
            from api.workers.tier2_fast.populate_race_results import populate_race_results

            TaskManager.enqueue_if_needed(
                sub_key,
                populate_race_results,
                int(year),
                int(round_number),
                session_type,
            )

        # Session-level data (weather, incidents, pit stops) for the race session
        # Dispatch all 3 fast workers for session data
        for sub_type in ["weather", "pit_stops", "incidents"]:
            sub_key = f"{sub_type}:{int(year)}:{int(round_number)}:R"
            if sub_type == "weather":
                from api.workers.tier2_fast.populate_weather import populate_weather
                TaskManager.enqueue_if_needed(sub_key, populate_weather, int(year), int(round_number), "R")
            elif sub_type == "pit_stops":
                from api.workers.tier2_fast.populate_pit_stops import populate_pit_stops
                TaskManager.enqueue_if_needed(sub_key, populate_pit_stops, int(year), int(round_number), "R")
            elif sub_type == "incidents":
                from api.workers.tier2_fast.populate_incidents import populate_incidents
                TaskManager.enqueue_if_needed(sub_key, populate_incidents, int(year), int(round_number), "R")

        pubsub.publish_result(task_key, {"source": "worker"})
        TaskRecord.objects.filter(task_key=task_key).update(status="complete", completed_at=timezone.now())
        logger.info(
            "event=celery_success task=prefetch_race_weekend task_key=%s year=%s round=%s",
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
            "event=celery_failed task=prefetch_race_weekend task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
