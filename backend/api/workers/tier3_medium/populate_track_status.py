from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, TrackStatusData
from api.services.unified_service import SessionManager, TrackStatusExtractor
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_track_status(self, task_key: str, year: int, round_number: int, session_type: str, **kwargs):
    """
    Populate track status (safety car, virtual safety car, weather, etc.) for a race session.
    
    Publishes full serialized track status payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_track_status task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        session = SessionManager.get_session(year, round_number, session_type, required_types=["track_status"])
        extractor = TrackStatusExtractor(session, year, round_number, session_type)
        data = extractor.extract()
        
        meta = data.setdefault("meta", {})
        meta["can_proceed"] = True
        avail = meta.setdefault("available_data", [])
        if "track_status" not in avail:
            avail.append("track_status")
        
        cache_key = f"track_status:{year}:{round_number}:{session_type}"

        worker_utils.handle_result(
            task_key=task_key,
            data_type="track_status",
            serialized_data=data,
            cache_key=cache_key,
        )

        # Save to DB
        TrackStatusData.objects.update_or_create(
            year=int(year),
            round_number=int(round_number),
            session=session_type,
            defaults={"payload": data}
        )
        
        logger.info(
            "event=celery_success task=populate_track_status task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_track_status task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")