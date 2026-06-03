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
    driver_code: str,
):
    """
    Populate DriverTelemetry for one driver — all laps stored in a single row.
    Task key: telemetry:{year}:{round}:{session}:{driver_code}
    
    Publishes full serialized telemetry payload via pub/sub and caches for non-blocking responses.
    """
    logger.info(
        "event=celery_start task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
        task_key, year, round_number, session_type, driver_code,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_telemetry import run
        run(
            year=int(year),
            round_number=int(round_number),
            session_type=str(session_type),
            driver_code=str(driver_code),
        )
        
        # Step 1: Fetch persisted telemetry
        telemetry = DriverTelemetry.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session_type),
            driver_code=str(driver_code),
        ).values()
        telemetry_list = list(telemetry) if telemetry else []
        
        # Step 2: Serialize
        serializer = TelemetryAnalysisResponseSerializer(telemetry_list, many=True)
        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"telemetry:{year}:{round_number}:{session_type}:{driver_code}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="telemetry",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_telemetry command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s records=%d",
            task_key, year, round_number, session_type, driver_code, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
