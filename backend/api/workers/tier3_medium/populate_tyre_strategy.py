from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord
from api.serializers import TyreStrategyResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_tyre_strategy(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Compute tyre strategy analysis (tire compounds, life, strategy) for a race session.
    Task key: tyre_strategy:{year}:{round}:{session}
    
    This is a derived analysis worker — no DB writes, only serialize + publish + cache.
    """
    logger.info("event=celery_start task=populate_tyre_strategy task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.workers.endpoint_load_map import get_session_load_kwargs
        from api.services.fastf1_runtime import get_session
        
        # Step 1: Load session with proper flags
        load_kwargs = get_session_load_kwargs("tyre_strategy")
        session = get_session(int(year), int(round_number), str(session_type))
        session.load(**load_kwargs)
        
        # Step 2: Compute analysis from session
        # TODO: Replace with actual tyre strategy function once available
        analysis_data = [
            {
                "year": year,
                "round_number": round_number,
                "session": session_type,
                "message": "Tyre strategy analysis not yet implemented"
            }
        ]
        
        # Step 3: Serialize
        serializer = TyreStrategyResponseSerializer(analysis_data, many=True)
        serialized_data = serializer.data
        
        # Step 4: Use worker_utils to handle result (no DB persistence)
        cache_key = f"tyre_strategy:{year}:{round_number}:{session_type}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="tyre_strategy",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_tyre_strategy task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_tyre_strategy task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")