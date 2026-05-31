from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_session_data(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate unified SessionData (weather, pit_stops, incidents, positions, drs, track_status).
    Task key: session_data:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=populate_session_data task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_session import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_session_data task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
