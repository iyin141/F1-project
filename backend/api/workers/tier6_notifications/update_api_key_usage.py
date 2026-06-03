from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.models import TaskRecord
import traceback
from api.models.auth import APIKey

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def update_api_key_usage(self, task_key: str, api_key_id: str, increment: int = 1):
    logger.info("event=celery_start task=update_api_key_usage task_key=%s api_key_id=%s increment=%d", task_key, api_key_id, increment)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())
    try:
        api_key = APIKey.objects.filter(id=api_key_id).first()
        if not api_key:
            raise ValueError(f"APIKey not found: {api_key_id}")
        api_key.request_count = (api_key.request_count or 0) + increment
        api_key.save(update_fields=["request_count"])
        pubsub.publish_result(task_key, {"source": "worker"})
        TaskRecord.objects.filter(task_key=task_key).update(status="complete", completed_at=timezone.now())
        logger.info("event=celery_success task=update_api_key_usage task_key=%s api_key_id=%s", task_key, api_key_id)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=update_api_key_usage task_key=%s error=%s", task_key, exc)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
