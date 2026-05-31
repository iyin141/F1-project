from celery import shared_task
import logging

from api.services.task_manager import TaskManager
from api.models.auth import APIKey

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def update_api_key_usage(self, task_key: str, api_key_id: str, increment: int = 1):
    logger.info("event=celery_start task=update_api_key_usage task_key=%s api_key_id=%s increment=%d", task_key, api_key_id, increment)
    TaskManager.mark_running(task_key)
    try:
        api_key = APIKey.objects.filter(id=api_key_id).first()
        if not api_key:
            raise ValueError(f"APIKey not found: {api_key_id}")
        api_key.request_count = (api_key.request_count or 0) + increment
        api_key.save(update_fields=["request_count"])
        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=update_api_key_usage task_key=%s api_key_id=%s", task_key, api_key_id)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=update_api_key_usage task_key=%s error=%s", task_key, exc)
        raise
