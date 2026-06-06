from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, PitStopData
from api.services.unified_service import SessionManager, PitStopExtractor
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_pit_stops(self, task_key: str, year: int, round_number: int, session_type: str = "R", **kwargs):
    """
    Populate pit stop data for a race.
    
    Publishes full serialized pit stops payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_pit_stops task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        limit = kwargs.get("limit")
        session = SessionManager.get_session(year, round_number, session_type, required_types=["pit_stops"])
        extractor = PitStopExtractor(session, year, round_number, session_type, limit=limit)
        data = extractor.extract()
        
        meta = data.setdefault("meta", {})
        meta["can_proceed"] = True
        avail = meta.setdefault("available_data", [])
        if "pit_stops" not in avail:
            avail.append("pit_stops")
        
        cache_key = f"pit_stops:{year}:{round_number}:{session_type}"
        if limit:
            cache_key += f":limit:{limit}"

        worker_utils.handle_result(
            task_key=task_key,
            data_type="pit_stops",
            serialized_data=data,
            cache_key=cache_key,
        )

        # Guarantee full session persistence
        if limit is not None:
            full_extractor = PitStopExtractor(session, year, round_number, session_type, limit=None)
            full_data = full_extractor.extract()
            full_data.setdefault("meta", {})["can_proceed"] = True
            if "pit_stops" not in full_data["meta"].setdefault("available_data", []):
                full_data["meta"]["available_data"].append("pit_stops")
        else:
            full_data = data

        PitStopData.objects.update_or_create(
            year=int(year),
            round_number=int(round_number),
            session=session_type,
            defaults={"payload": full_data}
        )
        
        logger.info(
            "event=celery_success task=populate_pit_stops task_key=%s year=%s round=%s",
            task_key, year, round_number
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_pit_stops task_key=%s year=%s round=%s", task_key, year, round_number)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
