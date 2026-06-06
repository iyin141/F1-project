from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache
import traceback

from api.services import pubsub, worker_utils
from api.models import TaskRecord
from api.sync_functions.sync_drivers import sync_season_drivers

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def sync_drivers_task(self, task_key: str, year: int):
    logger.info("event=celery_start task=sync_drivers_task task_key=%s year=%s", task_key, year)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        # Call the refactored sync function that does bulk operations
        result = sync_season_drivers(year)

        # Now query the updated drivers to stream back to the client
        from api.models.drivers import F1Driver
        drivers = F1Driver.objects.filter(seasons__contains=[year]).order_by('family_name', 'given_name')
        
        serialized_drivers = []
        for d in drivers:
            serialized_drivers.append({
                "driver_id": d.driver_id or None,
                "driver_code": d.code or None,
                "driver_name": f"{d.given_name or ''} {d.family_name or ''}".strip(),
                "nationality": d.nationality or None,
                "number": d.number or None,
                "seasons": d.seasons or [],
            })

        payload = {
            "year": year,
            "count": len(serialized_drivers),
            "drivers": serialized_drivers,
            "sync_result": result
        }

        # Publish and cache
        worker_utils.handle_result(
            task_key=task_key,
            data_type="driver_list",
            serialized_data=payload,
            cache_key=f"driver_list:{year}",
            year=year,
        )

        logger.info("event=celery_success task=sync_drivers_task task_key=%s year=%s", task_key, year)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now(), error_message=traceback.format_exc())
        logger.exception("event=celery_failed task=sync_drivers_task task_key=%s year=%s", task_key, year)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
