from celery import shared_task
import logging
import json

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, SeasonSchedule
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_schedule(self, task_key: str, year: int):
    """
    Populate SeasonSchedule for a season year.
    Task key: schedule:{year}
    
    Publishes full serialized schedule payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_schedule task_key=%s year=%s", task_key, year)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_schedule import run
        run(year=int(year))
        
        # Step 1: Fetch persisted schedule
        schedule = SeasonSchedule.objects.filter(year=int(year)).values()
        schedule_list = list(schedule) if schedule else []
        
        # Step 2: Serialize (SeasonSchedule already returns dict-compatible data)
        serialized_data = schedule_list
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"season_schedule:{year}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="season_schedule",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_schedule command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_schedule task_key=%s year=%s races=%d",
            task_key, year, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_schedule task_key=%s year=%s", task_key, year)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
