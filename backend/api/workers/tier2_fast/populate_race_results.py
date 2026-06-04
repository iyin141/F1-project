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
    "Q": ("qualifying", QualifyingResultSerializer),
    "FP1": ("practice_results", PracticeResultSerializer),
    "FP2": ("practice_results", PracticeResultSerializer),
    "FP3": ("practice_results", PracticeResultSerializer),
    "S": ("sprint_results", RaceResultsSerializer),
    "SQ": ("sprint_shootout", RaceResultsSerializer),
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
    
    # Compute canonical task key for this session type and update both legacy and canonical records
    if session_type == "R":
        canonical_task_key = f"race_results:{int(year)}:{int(round_number)}"
    elif session_type == "Q":
        canonical_task_key = f"qualifying:{int(year)}:{int(round_number)}"
    elif session_type == "S":
        canonical_task_key = f"sprint_results:{int(year)}:{int(round_number)}"
    elif session_type == "SQ":
        canonical_task_key = f"sprint_shootout:{int(year)}:{int(round_number)}"
    else:
        data_type, _ = _SESSION_SERIALIZERS.get(session_type, ("race_results", RaceResultsSerializer))
        canonical_task_key = f"{data_type}:{int(year)}:{int(round_number)}:{session_type}"

    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(
        status="running", 
        started_at=timezone.now()
    )

    try:
        # Load and run the populate_race management command
        from api.management.commands.populate_race import run
        run(year=int(year), round_number=int(round_number), session_type=str(session_type))
        
        # Step 1 & 2: Load session and format data using the service function
        from api.results.services.race import get_race_session_results
        from api.results.helpers import _load_session_with_readiness
        
        data_type, serializer_class = _SESSION_SERIALIZERS.get(session_type, ("race_results", RaceResultsSerializer))
        
        if session_type == "R":
            session, readiness = _load_session_with_readiness(
                int(year), 
                int(round_number), 
                'R',
                require_results=True,
                require_laps=True,
            )
            race_rows = get_race_session_results(session)
            structured_data = {"race": race_rows, "qualifying": []}
            serializer = serializer_class(instance=structured_data)
            
        elif session_type == "Q":
            session, readiness = _load_session_with_readiness(
                int(year),
                int(round_number),
                'Q',
                require_results=True,
            )
            from api.results.services.qualifying import get_qualifying_session_results
            qual_rows = get_qualifying_session_results(session)
            serializer = serializer_class(qual_rows, many=True)
            
        else:
            # Handle FP1/2/3, S, SQ similarly
            session, readiness = _load_session_with_readiness(
                int(year),
                int(round_number),
                session_type,
                require_results=True,
            )
            from api.results.services.practice import get_practice_session_results
            practice_rows = get_practice_session_results(session)
            serializer = serializer_class(practice_rows, many=True)

        serialized_data = serializer.data
        
        # Step 3: Use worker_utils to handle result (publish + cache + complete)
        # Use canonical cache keys so views/services can read them
        if session_type == "R":
            cache_key = f"race_results:{year}:{round_number}"
        elif session_type == "Q":
            cache_key = f"qualifying:{year}:{round_number}"
        elif session_type == "S":
            cache_key = f"sprint_results:{year}:{round_number}"
        elif session_type == "SQ":
            cache_key = f"sprint_shootout:{year}:{round_number}"
        else:
            cache_key = f"{data_type}:{year}:{round_number}:{session_type}"
            
        worker_utils.handle_result(
            task_key=canonical_task_key,
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
        try:
            cache.delete(f"task_lock:{canonical_task_key}")
        except Exception:
            pass