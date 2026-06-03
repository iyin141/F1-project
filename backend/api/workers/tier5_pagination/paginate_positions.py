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


@shared_task(bind=True, max_retries=1, queue="tier5_pagination")
def paginate_positions(self, task_key: str, year: int, round_number: int, session: str, page: int = 1, page_size: int = 50):
    """
    Paginate and serialize position data for a session.
    Task key: paginate_positions:{year}:{round}:{session}:{page}
    
    Publishes full serialized paginated positions payload via pub/sub and caches for non-blocking responses.
    """
    logger.info(
        "event=celery_start task=paginate_positions task_key=%s year=%s round=%s session=%s page=%d page_size=%d",
        task_key, year, round_number, session, page, page_size,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())
    
    try:
        # Step 1: Fetch paginated position data from DB
        offset = (int(page) - 1) * int(page_size)
        rows = PositionData.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session),
        )[offset:offset+int(page_size)].values()
        rows_list = list(rows)
        
        # Step 2: Serialize
        serializer = PositionResponseSerializer(rows_list, many=True)
        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"paginate_positions:{year}:{round_number}:{session}:{page}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="paginate_positions",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=paginate_positions task_key=%s year=%s round=%s session=%s page=%d records=%d",
            task_key, year, round_number, session, page, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=paginate_positions task_key=%s", task_key)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
