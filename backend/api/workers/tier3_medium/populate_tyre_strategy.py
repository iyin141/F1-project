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
def populate_tyre_strategy(self, task_key: str, year: int, round_number: int, session_type: str, **kwargs):
    """
    Compute tyre strategy analysis for a race session.
    """
    logger.info("event=celery_start task=populate_tyre_strategy task_key=%s year=%s round=%s session=%s", task_key, year, round_number, session_type)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.services.analysis import get_tyre_strategy_analysis
        from api.views import _ensure_payload_meta_checklist
        from api.serializers import TyreStrategyResponseSerializer
        
        # Step 1: Compute analysis (blocks and loads FastF1 if DB miss)
        analysis_payload = get_tyre_strategy_analysis(
            year=year,
            round_number=round_number,
            session=session_type,
            driver=kwargs.get("driver"),
            limit=kwargs.get("limit"),
        )
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ["laps"], [])
        
        # Step 2: Serialize
        serializer = TyreStrategyResponseSerializer(analysis_payload)
        serialized_data = serializer.data
        
        # Step 3: Publish and cache result
        worker_utils.handle_result(
            task_key=task_key,
            data_type="tyre_strategy",
            serialized_data=serialized_data,
            cache_key=task_key,
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