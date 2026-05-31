from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="backfill", rate_limit="3/m")
def seed_historical_round(self, task_key: str, year: int, round_number: int, data_types: list):
    """
    Seed a single historical round for the given data_types.

    Dispatches sub-tasks (populate_race_results / populate_session_data) for
    each requested type so that backfill can be interrupted and resumed without
    losing partial progress.

    Task key: seed_round:{year}:{round}
    Phase 6: Dispatched by seed_historical management command / seeding service.
    """
    logger.info(
        "event=celery_start task=seed_historical_round task_key=%s year=%s round=%s types=%s",
        task_key, year, round_number, data_types,
    )
    TaskManager.mark_running(task_key)

    try:
        from api.tasks import _SEED_SESSION_MAP

        for dtype in data_types:
            session_type = _SEED_SESSION_MAP.get(dtype)
            if session_type:
                sub_key = f"race_results:{int(year)}:{int(round_number)}:{session_type}"
                # import target task dynamically to avoid import cycles
                from api.workers.tier2_fast.populate_race_results import populate_race_results

                TaskManager.enqueue_if_needed(
                    sub_key,
                    populate_race_results,
                    int(year),
                    int(round_number),
                    session_type,
                )
            elif dtype == "session_data":
                sub_key = f"session_data:{int(year)}:{int(round_number)}:R"
                from api.workers.tier2_fast.populate_session_data import populate_session_data

                TaskManager.enqueue_if_needed(
                    sub_key,
                    populate_session_data,
                    int(year),
                    int(round_number),
                    "R",
                )

        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception(
            "event=celery_failed task=seed_historical_round task_key=%s year=%s round=%s",
            task_key, year, round_number,
        )
        raise
