from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_standings(self, task_key: str, year: int):
    """
    Populate DriverStandings for a season year.
    Task key: standings:{year}
    """
    logger.info("event=celery_start task=populate_standings task_key=%s year=%s", task_key, year)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_standings import run
        run(year=int(year))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_standings task_key=%s year=%s", task_key, year)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_standings task_key=%s year=%s", task_key, year)
        raise
