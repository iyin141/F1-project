from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_race_results(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate race results (R, Q, FP1-3, S, SQ).
    Task key: race_results/qualifying/practice/sprint_results/sprint_shootout:{year}:{round}
    """
    logger.info(
        "event=celery_start task=populate_race_results task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.management.commands.populate_race import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
