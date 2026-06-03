from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverTelemetry
from api.serializers import TelemetryOverlayResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_telemetry_overlay(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    driver_a: str,
    driver_b: str,
    lap_a: int = None,
    lap_b: int = None,
):
    """
    Populate dual-driver telemetry overlay for comparison.
    Task key: telemetry_overlay:{year}:{round}:{session}:{driver_a}:{driver_b}
    
    Fetches telemetry for both drivers and publishes aligned traces for overlay visualization.
    """
    logger.info(
        "event=celery_start task=populate_telemetry_overlay task_key=%s year=%s round=%s session=%s driver_a=%s driver_b=%s lap_a=%s lap_b=%s",
        task_key, year, round_number, session_type, driver_a, driver_b, lap_a, lap_b,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_telemetry import run
        
        # Step 1: Fetch telemetry for both drivers
        run(
            year=int(year),
            round_number=int(round_number),
            session_type=str(session_type),
            driver_code=str(driver_a),
        )
        run(
            year=int(year),
            round_number=int(round_number),
            session_type=str(session_type),
            driver_code=str(driver_b),
        )
        
        # Step 2: Fetch persisted telemetry for both drivers
        telemetry_a = DriverTelemetry.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session_type),
            driver_code=str(driver_a),
        ).values()
        
        telemetry_b = DriverTelemetry.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session_type),
            driver_code=str(driver_b),
        ).values()
        
        telemetry_a = list(telemetry_a) if telemetry_a else []
        telemetry_b = list(telemetry_b) if telemetry_b else []
        
        # Step 3: Serialize with overlay serializer
        serializer = TelemetryOverlayResponseSerializer(
            {
                "driver_a": telemetry_a,
                "driver_b": telemetry_b,
            }
        )
        serialized_data = serializer.data
        
        # Step 4: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"telemetry_overlay:{year}:{round_number}:{session_type}:{driver_a}:{driver_b}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="telemetry_overlay",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_telemetry_overlay task_key=%s year=%s round=%s session=%s driver_a=%s driver_b=%s",
            task_key, year, round_number, session_type, driver_a, driver_b,
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
