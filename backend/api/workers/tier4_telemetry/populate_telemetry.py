from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_telemetry(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    driver_code: str,
):
    """
    Populate DriverTelemetry for one driver — all laps stored in a single row.
    Task key: telemetry:{year}:{round}:{session}:{driver_code}
    """
    logger.info(
        "event=celery_start task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
        task_key, year, round_number, session_type, driver_code,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_telemetry import run
        run(
            year=int(year),
            round_number=int(round_number),
            session_type=str(session_type),
            driver_code=str(driver_code),
        )
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
        raise
