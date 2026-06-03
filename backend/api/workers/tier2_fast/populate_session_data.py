from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_session_data(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate unified SessionData (weather, pit_stops, incidents, positions, drs, track_status).
    Task key: session_data:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=populate_session_data task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_session import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        
        # Use worker_utils to handle result properly
        worker_utils.handle_result(
            task_key=task_key,
            data_type="session_data",
            serialized_data={"populated": True},
            cache_key=f"session_data:{year}:{round_number}:{session_type.upper()}",
        )
        
        logger.info(
            "event=celery_success task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
