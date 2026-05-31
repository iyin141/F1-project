from celery import shared_task
import logging

from api.services.task_manager import TaskManager
from .email_helpers import send_plain_api_key_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_api_key_email(self, task_key: str, api_key_id: str, email: str, verification_link: str):
    logger.info("event=celery_start task=send_api_key_email task_key=%s email=%s", task_key, email)
    TaskManager.mark_running(task_key)
    try:
        send_plain_api_key_email(api_key_id, email)

        TaskManager.mark_complete(task_key)
        logger.info("event=celery_success task=send_api_key_email task_key=%s", task_key)
    except Exception as exc:
        TaskManager.mark_failed(task_key, exc)
        logger.exception("event=celery_failed task=send_api_key_email task_key=%s error=%s", task_key, exc)
        raise
