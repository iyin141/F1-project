from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_incidents(self, task_key: str, year: int, round_number: int):
    """
    Populate incidents/race control messages for a race.
    Task key: incidents:{year}:{round}
    Phase 6: Used in race completion prefetching and historical seeding.
    """
    logger.info("event=celery_start task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        # Incidents loaded as part of race results
        run(year=int(year), round_number=int(round_number), session_type="R")
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_incidents task_key=%s year=%s round=%s", task_key, year, round_number)
        raise
