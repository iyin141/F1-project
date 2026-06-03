from celery import shared_task
import logging

from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, RaceResultData
from api.serializers import RaceResultsSerializer, QualifyingResultSerializer, PracticeResultSerializer
import traceback

logger = logging.getLogger(__name__)

_SESSION_SERIALIZERS = {
    "R": ("race_results", RaceResultsSerializer),
    "Q": ("qualifying_results", QualifyingResultSerializer),
    "FP1": ("practice_results", PracticeResultSerializer),
    "FP2": ("practice_results", PracticeResultSerializer),
    "FP3": ("practice_results", PracticeResultSerializer),
    "S": ("race_results", RaceResultsSerializer),
    "SQ": ("race_results", RaceResultsSerializer),
}


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_race_results(self, task_key: str, year: int, round_number: int, session_type: str):
    """
    Populate race results (R, Q, FP1-3, S, SQ).
    Task key: race_results/qualifying/practice/sprint_results/sprint_shootout:{year}:{round}
    
    Publishes full serialized result payload via pub/sub and caches for non-blocking responses.
    """
    logger.info(
        "event=celery_start task=populate_race_results task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.management.commands.populate_race import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        
        # Step 1: Fetch persisted race results
        results = RaceResultData.objects.filter(
            year=int(year),
            round_number=int(round_number),
            session=str(session_type),
        ).values()
        
        if not results:
            logger.warning("event=no_results_persisted task_key=%s", task_key)
            results = []
        else:
            results = list(results)
        
        # Step 2: Serialize with session-appropriate serializer
        data_type, serializer_class = _SESSION_SERIALIZERS.get(session_type, ("race_results", RaceResultsSerializer))
        serializer = serializer_class(results, many=True)
        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        cache_key = f"{data_type}:{year}:{round_number}:{session_type}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type=data_type,
            serialized_data=serialized_data,
            cache_key=cache_key,
            db_rows=None,  # Results already persisted by populate_race command
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_race_results task_key=%s year=%s round=%s session=%s results=%d",
            task_key, year, round_number, session_type, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
            error_message=traceback.format_exc(),
        )
        logger.exception(
            "event=celery_failed task=populate_race_results task_key=%s year=%s round=%s session=%s",
            task_key, year, round_number, session_type,
        )
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
