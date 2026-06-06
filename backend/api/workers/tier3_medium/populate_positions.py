from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, PositionData
from api.services.unified_service import SessionManager, PositionExtractor
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_positions(self, task_key: str, year: int, round_number: int, session_type: str, **kwargs):
    """
    Populate position data for a race session.
    
    Publishes full serialized positions payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_positions task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        sample_interval = kwargs.get("sample_interval", 5)
        session = SessionManager.get_session(year, round_number, session_type, required_types=["positions"])
        extractor = PositionExtractor(session, year, round_number, session_type)
        data = extractor.extract(sample_interval=sample_interval)
        
        meta = data.setdefault("meta", {})
        meta["can_proceed"] = True
        avail = meta.setdefault("available_data", [])
        if "positions" not in avail:
            avail.append("positions")
        
        cache_key = f"positions:{year}:{round_number}:{session_type}:interval:{sample_interval}"

        worker_utils.handle_result(
            task_key=task_key,
            data_type="positions",
            serialized_data=data,
            cache_key=cache_key,
        )

        # Guarantee full session persistence
        if sample_interval != 5:
            full_extractor = PositionExtractor(session, year, round_number, session_type)
            full_data = full_extractor.extract(sample_interval=5)
            full_data.setdefault("meta", {})["can_proceed"] = True
            if "positions" not in full_data["meta"].setdefault("available_data", []):
                full_data["meta"]["available_data"].append("positions")
        else:
            full_data = data

        PositionData.objects.update_or_create(
            year=int(year),
            round_number=int(round_number),
            session=session_type,
            defaults={"payload": full_data}
        )
        
        logger.info(
            "event=celery_success task=populate_positions task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_positions task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
