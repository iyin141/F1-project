from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_career(self, task_key: str, driver_code: str):
    """
    Populate DriverCareer for a driver.
    Task key: driver_career:{driver_code}
    """
    logger.info("event=celery_start task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_driver_career import run
        run(driver_code=str(driver_code))
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
        raise
