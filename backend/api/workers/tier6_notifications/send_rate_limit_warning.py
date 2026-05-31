from celery import shared_task
import logging

from api.workers.tier6_notifications.send_rate_limit_warning_email import send_rate_limit_warning_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_rate_limit_warning(self, task_key: str, api_key_id: str, email: str, usage_percent: int):
    logger.info("event=celery_start task=send_rate_limit_warning task_key=%s email=%s usage=%d%%", task_key, email, usage_percent)
    try:
        send_rate_limit_warning_email.apply_async(
            args=(task_key, api_key_id, email, usage_percent),
            queue="tier6_notifications",
        )
        logger.info("event=celery_success task=send_rate_limit_warning task_key=%s", task_key)
    except Exception as exc:
        logger.exception("event=celery_failed task=send_rate_limit_warning task_key=%s error=%s", task_key, exc)
        raise
