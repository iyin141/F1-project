from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=1, queue="tier5_pagination")
def paginate_telemetry(self, task_key: str, year: int, round_number: int, session: str, page_size: int = 50):
    """
    Paginate telemetry data for a session.
    Task key: paginate_telemetry:{year}:{round}:{session}
    """
    logger.info(
        "event=celery_start task=paginate_telemetry task_key=%s year=%s round=%s session=%s page_size=%d",
        task_key, year, round_number, session, page_size,
    )
    TaskManager.mark_running(task_key)
    
    try:
        from api.services.pagination_cache import set_paginated_data
        from api.services.cache import ttl_for

        telemetry_data = []  # TODO: replace with real data retrieval

        ttl = ttl_for("telemetry", year)
        set_paginated_data(year, round_number, session, "telemetry", telemetry_data, page_size, ttl)

        TaskManager.mark_complete(task_key)
        logger.info(
            "event=celery_success task=paginate_telemetry task_key=%s year=%s round=%s session=%s pages=%d",
            task_key, year, round_number, session,
            (len(telemetry_data) + page_size - 1) // page_size if telemetry_data else 0,
        )
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=paginate_telemetry task_key=%s", task_key)
        raise
