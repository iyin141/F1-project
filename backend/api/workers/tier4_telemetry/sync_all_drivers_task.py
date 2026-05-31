from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry")
def sync_all_drivers_task(self, task_key: str, start: int = 1950, end: int = 2025):
    """
    Sync drivers for all seasons (1950–2025) asynchronously via Celery.
    Task key: sync_drivers_all
    """
    logger.info(
        "event=celery_start task=sync_all_drivers_task task_key=%s start=%s end=%s",
        task_key, start, end,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.sync_service import DriverSyncService
        service = DriverSyncService()
        result = service.sync_all_seasons(start=int(start), end=int(end))
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=sync_all_drivers_task task_key=%s total_synced=%d total_errors=%d",
            task_key, result.get("total_synced", 0), result.get("total_errors", 0),
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_all_drivers_task task_key=%s", task_key)
        raise
