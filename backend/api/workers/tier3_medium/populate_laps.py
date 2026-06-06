from celery import shared_task
import logging

from django.utils import timezone
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord
from api.serializers import LapAnalysisRowSerializer
import traceback

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def populate_laps(self, task_key: str, year: int, round_number: int, session_type: str, **kwargs):
    """
    Compute lap-level analysis for a race session.
    Saves full driver lap analysis to DB if it doesn't already exist.
    """
    logger.info(
        "event=celery_start task=populate_laps task_key=%s year=%s round=%s session=%s",
        task_key, year, round_number, session_type,
    )
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from api.services.analysis import get_lap_analysis
        from api.views import _ensure_payload_meta_checklist
        from api.serializers import LapAnalysisResponseSerializer
        
        # Step 1: Ensure DB is populated
        from api.models import DriverLapAnalysis
        has_data = DriverLapAnalysis.objects.filter(year=year, round_number=round_number, session=session_type).exists()
        if not has_data:
            # We must load and persist!
            from api.results.helpers import _load_session_with_readiness
            from api.results.parsing import parse_session_once
            from api.services.store import bulk_store_driver_lap_analysis
            
            logger.info("event=populate_laps_persisting year=%s round=%s session=%s", year, round_number, session_type)
            session, readiness = _load_session_with_readiness(
                int(year), int(round_number), session_type, require_laps=True,
            )
            parsed = parse_session_once(session, year=int(year), round_number=int(round_number), session_type=session_type)
            
            try:
                bulk_store_driver_lap_analysis(
                    year=int(year),
                    round_number=int(round_number),
                    session=session_type,
                    parsed_session=parsed,
                )
            except Exception as e:
                logger.error("Failed to bulk store driver laps: %s", e)
        
        # Step 2: Now fetch the data. If DB was just populated, it will use the DB.
        # Otherwise, get_lap_analysis will fetch whatever is appropriate.
        analysis_payload = get_lap_analysis(
            year=year,
            round_number=round_number,
            session=session_type,
            driver=kwargs.get("driver"),
            limit=kwargs.get("limit"),
        )
        analysis_payload = _ensure_payload_meta_checklist(analysis_payload, ["laps"], [])
        
        # Step 3: Serialize
        serializer = LapAnalysisResponseSerializer(analysis_payload)
        serialized_data = serializer.data
        
        # Step 4: Publish and cache result
        worker_utils.handle_result(
            task_key=task_key,
            data_type="laps",
            serialized_data=serialized_data,
            cache_key=task_key,
            db_rows=None,
            db_model=None,
        )
        
        logger.info(
            "event=celery_success task=populate_laps task_key=%s year=%s round=%s session=%s results=%d",
            task_key, year, round_number, session_type, len(serialized_data),
        )
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(
            status="failed",
            completed_at=timezone.now(),
        )
        logger.error(
            "event=celery_exception task=populate_laps task_key=%s error=%s traceback=%s",
            task_key, str(exc), traceback.format_exc(),
        )
        raise
    finally:
        try:
            cache.delete(f"task_lock:{task_key}")
            cache.delete(f"task_lock:{canonical_task_key}")
        except Exception:
            pass
