import logging
import traceback
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache

from api.models import TaskRecord
from api.management.commands.populate_telemetry import run as run_populate_telemetry

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_driver_telemetry(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
    driver_code: str,
):
    """
    Populate DriverTelemetry for one driver — all laps stored in a single row.
    """
    logger.info(
        "event=celery_start task=populate_driver_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
        task_key, year, round_number, session_type, driver_code,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        run_populate_telemetry(
            year=year,
            round_number=round_number,
            session_type=session_type,
            driver_code=driver_code,
            stride=3,
        )
        TaskRecord.objects.filter(task_key=task_key).update(
            status="complete", completed_at=timezone.now()
        )
        logger.info(
            "event=celery_success task=populate_driver_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
    except Exception as exc:
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_driver_telemetry task_key=%s year=%s round=%s session=%s driver=%s",
            task_key, year, round_number, session_type, driver_code,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
