from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverTelemetry
from api.session.serializers import TelemetryOverlayResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_telemetry_overlay(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    **kwargs
):
    """
    Populate dual-driver telemetry overlay for comparison.
    """
    logger.info(
        "event=celery_start task=populate_telemetry_overlay task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.services.analysis import get_telemetry_overlay
        from api.core import _ensure_payload_meta_checklist
        from api.session.serializers import TelemetryOverlayResponseSerializer
        
        # Step 1: Compute analysis (blocks and loads FastF1 if DB miss)
        analysis_payload = get_telemetry_overlay(
            year=year,
            round_number=round_number,
            session=session_type,
            driver_a=kwargs.get("driver_a"),
            driver_b=kwargs.get("driver_b"),
            lap_a=kwargs.get("lap_a"),
            lap_b=kwargs.get("lap_b"),
            limit_points=kwargs.get("limit_points"),
            stride=kwargs.get("stride", 1),
            sector_start=kwargs.get("sector_start"),
            sector_end=kwargs.get("sector_end"),
        )
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ["telemetry"], [])
        
        # Step 2: Serialize
        serializer = TelemetryOverlayResponseSerializer(analysis_payload)
        serialized_data = serializer.data
        
        # Step 3: Publish and cache result
        worker_utils.handle_result(
            task_key=task_key,
            data_type="telemetry_overlay",
            serialized_data=serialized_data,
            cache_key=task_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_telemetry_overlay task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
        )
        logger.error(
            "event=celery_exception task=populate_telemetry_overlay task_key=%s error=%s traceback=%s",
            task_key, str(exc), traceback.format_exc(),
        )
        raise
