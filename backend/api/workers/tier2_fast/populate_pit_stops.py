from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, PitStopData
from api.serializers import PitStopResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_pit_stops(self, task_key: str, year: int, round_number: int):
    """
    Populate pit stop data for a race.
    Task key: pit_stops:{year}:{round}
    
    Publishes full serialized pit stops payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_session import run
        # Extract pit stops via populate_session command
        run(year=int(year), round_number=int(round_number), session_type="R", only="pit_stops")
        
        # Step 1: Fetch extracted pit stops from DB
        record = PitStopData.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session="R"
        ).first()
        
        # Step 2: Get pre-serialized data from payload
        serialized_data = record.payload.get("data", []) if record else []
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"pit_stops:{year}:{round_number}:R"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="pit_stops",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_session command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_pit_stops task_key=%s year=%s round=%s records=%d",
            task_key, year, round_number, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
