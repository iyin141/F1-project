from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, WeatherData
from api.services.unified_service import SessionManager, WeatherExtractor
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_weather(self, task_key: str, year: int, round_number: int, session_type: str = "R", **kwargs):
    """
    Populate weather data for a race session.
    
    Publishes full serialized weather payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_weather task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        include_per_lap = kwargs.get("include_per_lap", False)
        required_types = ["weather", "laps"] if include_per_lap else ["weather"]
        session = SessionManager.get_session(year, round_number, session_type, required_types=required_types)
        extractor = WeatherExtractor(session, year, round_number, session_type)
        data = extractor.extract(include_per_lap=include_per_lap)
        
        meta = data.setdefault("meta", {})
        meta["can_proceed"] = True
        avail = meta.setdefault("available_data", [])
        if "weather" not in avail:
            avail.append("weather")
        
        # Save to DB if default options
        if not include_per_lap:
            WeatherData.objects.update_or_create(
                year=int(year),
                round_number=int(round_number),
                session=session_type,
                defaults={"payload": data}
            )

        cache_key = f"weather:{year}:{round_number}:{session_type}"
        if include_per_lap:
            cache_key += ":per_lap"

        worker_utils.handle_result(
            task_key=task_key,
            data_type="weather",
            serialized_data=data,
            cache_key=cache_key,
        )

        logger.info(
            "event=celery_success task=populate_weather task_key=%s year=%s round=%s",
            task_key, year, round_number
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_weather task_key=%s year=%s round=%s", task_key, year, round_number)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
