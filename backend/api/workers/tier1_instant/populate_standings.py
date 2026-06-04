from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverStandings
from api.serializers import DriverStandingsResponseSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_standings(self, task_key: str, year: int):
    """
    Populate DriverStandings for a season year.
    Task key: standings:{year}
    
    Publishes full serialized standings payload via pub/sub and caches for non-blocking responses.
    """
    logger.info("event=celery_start task=populate_standings task_key=%s year=%s", task_key, year)
    canonical_task_key = f"standings:{int(year)}"
    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_standings import run
        run(year=int(year))
        
        # Step 1: Fetch persisted standings
        standings = DriverStandings.objects.filter(year=int(year)).values()
        standings_list = list(standings) if standings else []
        
        # Step 2: Serialize
        serializer = DriverStandingsResponseSerializer(standings_list, many=True)
        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"driver_standings:{year}"
        worker_utils.handle_result(
            task_key=canonical_task_key,
            data_type="driver_standings",
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Already persisted by populate_standings command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_standings task_key=%s year=%s standings=%d",
            task_key, year, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception("event=celery_failed task=populate_standings task_key=%s year=%s", task_key, year)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
        cache.delete(f"task_lock:{canonical_task_key}")
