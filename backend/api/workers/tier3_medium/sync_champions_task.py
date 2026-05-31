from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def sync_champions_task(self, task_key: str, year: int = None):
    """
    Sync F1 champions from Jolpica into F1Champion table.
    Task key: sync_champions or sync_champions:{year}
    """
    logger.info("event=celery_start task=sync_champions_task task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.drivers.services.champions_sync_service import ChampionsSyncService
        service = ChampionsSyncService()

        if year:
            result = service.sync_year_champion(int(year))
        else:
            result = service.sync_all_champions()

        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=sync_champions_task task_key=%s result=%s", task_key, result)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=sync_champions_task task_key=%s", task_key)
        raise
