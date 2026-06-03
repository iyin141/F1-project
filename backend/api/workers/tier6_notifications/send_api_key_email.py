from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.models import TaskRecord
import traceback
from .email_helpers import send_plain_api_key_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_api_key_email(self, task_key: str, api_key_id: str, email: str, verification_link: str):
    logger.info("event=celery_start task=send_api_key_email task_key=%s email=%s", task_key, email)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())
    try:
        send_plain_api_key_email(api_key_id, email)

        pubsub.publish_result(task_key, {"source": "worker"})
        TaskRecord.objects.filter(task_key=task_key).update(status="complete", completed_at=timezone.now())
        logger.info("event=celery_success task=send_api_key_email task_key=%s", task_key)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=send_api_key_email task_key=%s error=%s", task_key, exc)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
