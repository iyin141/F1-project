from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, PositionData
from api.serializers import PositionResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_positions(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate position data for a race session.
    Task key: positions:{year}:{round}:{session}
    
    Publishes full serialized positions payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_positions task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    canonical_task_key = f"positions:{int(year)}:{int(round_number)}:{session_type}"
    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_session import run
        # Extract positions via populate_session command
        run(year=int(year), round_number=int(round_number), session_type=str(session_type), only="positions")
        
        # Step 1: Fetch extracted positions from DB
        record = PositionData.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session_type)
        ).first()
        
        # Step 2: Get pre-serialized data from payload
        serialized_data = record.payload.get("data", []) if record else []
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"positions:{year}:{round_number}:{session_type}"
        worker_utils.handle_result(
            task_key=canonical_task_key,
            data_type="positions",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_session command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_positions task_key=%s year=%s round=%s session=%s records=%d",
            task_key, year, round_number, session_type, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_positions task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
        cache.delete(f"task_lock:{canonical_task_key}")
