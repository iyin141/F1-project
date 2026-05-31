from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def sync_drivers_task(self, task_key: str, year: int):
    """
    Sync drivers for a single season asynchronously via Celery.
    Task key: sync_drivers:{year}
    """
    logger.info("event=celery_start task=sync_drivers_task task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.sync_service import DriverSyncService
        service = DriverSyncService()
        result = service.sync_season_drivers(int(year))
        
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=sync_drivers_task task_key=%s year=%s synced=%d errors=%d",
            task_key, year, result.get("synced", 0), result.get("errors", 0),
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_drivers_task task_key=%s year=%s", task_key, year)
        raise
