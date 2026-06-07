import logging
import traceback
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache

from api.models import TaskRecord
from api.management.commands.populate_telemetry import run as run_populate_telemetry

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier4_telemetry", ack_late=True)
def populate_session_telemetry(
    self,
    task_key: str,
    year: int,
    round_number: int,
    session_type: str,
):
    """
    Populate DriverTelemetry for an entire session — all drivers, all laps stored.
    """
    logger.info(
        "event=celery_start task=populate_session_telemetry task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        run_populate_telemetry(
            year=year,
            round_number=round_number,
            session_type=session_type,
            driver_code=None,
            stride=1,
        )
        TaskRecord.objects.filter(task_key=task_key).update(
            status="complete", completed_at=timezone.now()
        )
        logger.info(
            "event=celery_success task=populate_session_telemetry task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
    except Exception as exc:
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_session_telemetry task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
