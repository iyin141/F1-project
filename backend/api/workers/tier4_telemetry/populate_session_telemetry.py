import logging
import traceback
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache

from api.models import TaskRecord
from api.management.commands.populate_telemetry import run as run_populate_telemetry

logger = logging.getLogger(__name__)


def _queue_track_geometry(year, round_number, session_type):
    """v2: build the track map once a Q or R session's telemetry is stored.
    The build is idempotent; a failure here never fails ingestion."""
    from django.conf import settings
    if session_type not in ("Q", "R") or not getattr(settings, "TRACKMAP_AUTOBUILD", True):
        return
    try:
        from api.trackmap.tasks import build_track_geometry
        build_track_geometry.delay(year, round_number)
    except Exception:
        logger.exception("event=trackmap_enqueue_failed year=%s round=%s", year, round_number)

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
        _queue_track_geometry(year, round_number, session_type)
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
