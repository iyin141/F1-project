from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def prefetch_race_weekend(self, task_key: str, year: int, round_number: int):
    """
    Prefetch core data for a newly-completed race weekend.

    Loads race results, qualifying, and race session data (weather, incidents,
    pit stops).  Does NOT prefetch telemetry, positions, or DRS — those are
    expensive and should only be loaded on demand.

    Task key: prefetch:{year}:{round}
    Phase 6: Fired by check_for_completed_sessions beat task.
    """
    logger.info(
        "event=celery_start task=prefetch_race_weekend task_key=%s year=%s round=%s",
        task_key, year, round_number,
    )
    TaskManager.mark_running(task_key)

    try:
        # Race results + qualifying results
        for session_type, prefix in [("R", "race_results"), ("Q", "qualifying")]:
            sub_key = f"{prefix}:{int(year)}:{int(round_number)}"
            from api.workers.tier2_fast.populate_race_results import populate_race_results

            TaskManager.enqueue_if_needed(
                sub_key,
                populate_race_results,
                int(year),
                int(round_number),
                session_type,
            )

        # Session-level data (weather, incidents, pit stops) for the race session
        sd_key = f"session_data:{int(year)}:{int(round_number)}:R"
        from api.workers.tier2_fast.populate_session_data import populate_session_data

        TaskManager.enqueue_if_needed(
            sd_key,
            populate_session_data,
            int(year),
            int(round_number),
            "R",
        )

        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=prefetch_race_weekend task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=prefetch_race_weekend task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise
