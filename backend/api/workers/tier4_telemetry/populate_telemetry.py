from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverTelemetry
from api.serializers import TelemetryAnalysisResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_telemetry(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    **kwargs
):
    """
    Populate DriverTelemetry for one driver lap and return the snapshot.
    """
    logger.info(
        "event=celery_start task=populate_telemetry task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.services.analysis import get_telemetry_snapshot
        from api.views import _ensure_payload_meta_checklist
        from api.serializers import TelemetryAnalysisResponseSerializer
        
        # Step 1: Compute analysis (blocks and loads FastF1 if DB miss)
        analysis_payload = get_telemetry_snapshot(
            year=year,
            round_number=round_number,
            session=session_type,
            driver=kwargs.get("driver"),
            lap=kwargs.get("lap"),
            limit_points=kwargs.get("limit_points"),
            stride=kwargs.get("stride", 1),
            sector_start=kwargs.get("sector_start"),
            sector_end=kwargs.get("sector_end"),
        )
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ["telemetry"], [])
        
        # Step 2: Serialize
        serializer = TelemetryAnalysisResponseSerializer(analysis_payload)
        serialized_data = serializer.data
        
        # Step 3: Publish and cache result
        worker_utils.handle_result(
            task_key=task_key,
            data_type="telemetry",
            serialized_data=serialized_data,
            cache_key=task_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_telemetry task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_telemetry task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
