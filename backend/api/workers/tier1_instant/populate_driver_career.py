from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverCareer
from api.serializers import DriverCareerResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_career(self, task_key: str, driver_code: str):
    """
    Populate DriverCareer for a driver.
    Task key: driver_career:{driver_code}
    
    Publishes full serialized career payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_driver_career import run
        run(driver_code=str(driver_code))
        
        # Step 1: Fetch persisted career
        career = DriverCareer.objects.filter(driver_code=str(driver_code)).values()
        career_list = list(career) if career else []
        
        # Step 2: Serialize
        serializer = DriverCareerResponseSerializer(career_list, many=True)
        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"driver_career:{driver_code}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="driver_career",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_driver_career command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_driver_career task_key=%s driver=%s records=%d",
            task_key, driver_code, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
