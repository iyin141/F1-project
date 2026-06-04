from celery import shared_task
import logging

from django.utils import timezone
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord
from api.serializers import LapAnalysisRowSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_laps(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Compute lap-level analysis for a race session.
    Task key: laps:{year}:{round}:{session}
    
    This is a derived analysis worker — no DB writes, only serialize + publish + cache.
    """
    logger.info(
        "event=celery_start task=populate_laps task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    canonical_task_key = f"laps:{int(year)}:{int(round_number)}:{session_type}"
    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(status="running", started_at=timezone.now())

    try:
        from api.workers.endpoint_load_map import get_session_load_kwargs
        from api.services.fastf1_runtime import get_session
        
        # Step 1: Load session with proper flags
        load_kwargs = get_session_load_kwargs("laps")
        session = get_session(int(year), int(round_number), str(session_type))
        session.load(**load_kwargs)
        
        # Step 2: Compute analysis from session
        # TODO: Replace with actual lap analysis function once available
        analysis_data = [
            {
                "year": year,
                "round_number": round_number,
                "session": session_type,
                "message": "Lap analysis not yet implemented"
            }
        ]
        
        # Step 3: Serialize
        serializer = LapAnalysisRowSerializer(analysis_data, many=True)
        serialized_data = serializer.data
        
        # Step 4: Use worker_utils to handle result (no DB persistence)
        cache_key = f"laps:{year}:{round_number}:{session_type}"
        worker_utils.handle_result(
            task_key=canonical_task_key,
            data_type="laps",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_laps task_key=%s year=%s round=%s session=%s results=%d",
            task_key, year, round_number, session_type, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
        )
        logger.error(
            "event=celery_exception task=populate_laps task_key=%s error=%s traceback=%s",
            task_key, str(exc), traceback.format_exc(),
        )
        raise
    finally:
        try:
            cache.delete(f"task_lock:{task_key}")
            cache.delete(f"task_lock:{canonical_task_key}")
        except Exception:
            pass
