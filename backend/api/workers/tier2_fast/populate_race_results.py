from celery import shared_task
import logging

import time
from django.utils import timezone
from django.core.cache import cache
from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, RaceResultData, QualifyingResultData
from api.results.serializers import (
    RaceResultSerializer,
    QualifyingResultSerializer,
    PracticeResultSerializer,
    SprintResultSerializer,
    SprintShootoutResultSerializer,
)
from api.common.readiness import build_readiness
import traceback

logger = logging.getLogger(__name__)

_SESSION_SERIALIZERS = {
    "R": ("race_results", RaceResultSerializer),
    "Q": ("qualifying", QualifyingResultSerializer),
    "FP1": ("practice_results", PracticeResultSerializer),
    "FP2": ("practice_results", PracticeResultSerializer),
    "FP3": ("practice_results", PracticeResultSerializer),
    "S": ("sprint_results", SprintResultSerializer),
    "SQ": ("sprint_shootout", SprintShootoutResultSerializer),
}

def _save_race_results_to_db(year: int, round_number: int, race_rows: list | None):
    payload = {"data": race_rows or []}
    RaceResultData.objects.update_or_create(
        year=year,
        round_number=round_number,
        session="R",
        defaults={"payload": payload},
    )

def _fetch_and_save_qualifying(year: int, round_number: int):
    from api.results.services.qualifying import get_qualifying_results
    logger = logging.getLogger(__name__)
    try:
        start = time.time()
        qual_payload = get_qualifying_results(year, round_number)
        if isinstance(qual_payload, dict):
            qual_rows = qual_payload.get("data", [])
        else:
            qual_rows = qual_payload
        if not qual_rows:
            return
        payload = {"data": qual_rows}
        QualifyingResultData.objects.update_or_create(
            year=year,
            round_number=round_number,
            defaults={"payload": payload},
        )
    except Exception as e:
        logger.error("event=qualifying_save_failed year=%s round=%s error=%s", year, round_number, str(e))

@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_qualifying_results(self, year: int, round_number: int):
    _fetch_and_save_qualifying(int(year), int(round_number))


@shared_task(bind=True, max_retries=0, queue="tier2_fast")
def populate_race_results(self, task_key: str, year: int, round_number: int, session_type: str):
    logger.info("event=celery_start task=populate_race_results task_key=%s", task_key)
    
    if session_type == "R":
        canonical_task_key = f"race_results:{int(year)}:{int(round_number)}"
    elif session_type == "Q":
        canonical_task_key = f"qualifying:{int(year)}:{int(round_number)}"
    elif session_type == "S":
        canonical_task_key = f"sprint_results:{int(year)}:{int(round_number)}"
    elif session_type == "SQ":
        canonical_task_key = f"sprint_shootout:{int(year)}:{int(round_number)}"
    else:
        data_type, _ = _SESSION_SERIALIZERS.get(session_type, ("race_results", RaceResultSerializer))
        canonical_task_key = f"{data_type}:{int(year)}:{int(round_number)}:{session_type}"

    TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(
        status="running", started_at=timezone.now()
    )

    try:
        data_type, serializer_class = _SESSION_SERIALIZERS.get(session_type, ("race_results", RaceResultSerializer))

        from api.results.helpers import _load_session_with_readiness
        from api.results.parsing import parse_session_once
        from api.services.store import store_driver_lap_analysis

        session, readiness = _load_session_with_readiness(
            int(year), int(round_number), session_type, require_results=True, require_laps=True,
        )
        parsed = parse_session_once(session, year=int(year), round_number=int(round_number), session_type=session_type)

        # Build output structure based on session type
        if session_type == "R":
            rows = parsed.race_results
            serialized_rows = serializer_class(rows, many=True).data
            serialized_data = {
                "year": int(year), "round": int(round_number),
                "results": {"qualifying": [], "race": serialized_rows},
                "readiness": build_readiness(True, ["race_results"], ["qualifying_results"], "Qualifying data not yet available.")
            }
        elif session_type == "Q":
            rows = parsed.qualifying_results
            serialized_rows = serializer_class(rows, many=True).data
            serialized_data = {
                "year": int(year), "round": int(round_number), "qualifying": serialized_rows,
                "readiness": build_readiness(True, ["qualifying_results"], [], None)
            }
        elif session_type in ["S", "SQ"]:
            rows = parsed.race_results
            serialized_rows = serializer_class(rows, many=True).data
            key = "sprint" if session_type == "S" else "sprint_shootout"
            readiness_key = f"{key}_results"
            serialized_data = {
                "year": int(year), "round": int(round_number), key: serialized_rows,
                "readiness": build_readiness(True, [readiness_key], [], None)
            }
        else:
            rows = parsed.practice_results
            serialized_rows = serializer_class(rows, many=True).data
            serialized_data = {
                "year": int(year), "round": int(round_number), "session": session_type, "practice": serialized_rows,
                "readiness": build_readiness(True, ["practice_results"], [], None)
            }

        # Handle DB caching and fallback via standard wrapper
        # Ensure we're formatting exactly as nonblocking standard wrapped data
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

        # Standard Wrapper builder
        meta = {
            "year": int(year),
            "round": int(round_number),
            "session": session_type,
            "row_count": len(rows),
            "limit_max": 2000,
            "can_proceed": bool(rows),
            "available_data": serialized_data["readiness"].get("available_data", []),
            "unavailable_data": serialized_data["readiness"].get("unavailable_data", []),
            "message": serialized_data["readiness"].get("message"),
            "warnings": serialized_data["readiness"].get("warnings", []),
        }

        filters = {
            "driver": None,
            "limit": None
        }

        # Map correct wrapper data key
        if session_type == "R":
            data_payload = serialized_rows
        elif session_type == "Q":
            data_payload = serialized_rows
        elif session_type == "S":
            data_payload = serialized_rows
        elif session_type == "SQ":
            data_payload = serialized_rows
        else:
            data_payload = serialized_rows

        standardized_payload = {
            "meta": meta,
            "filters_applied": filters,
            "data": data_payload
        }
        
        if session_type == "R":
            standardized_payload["qualifying"] = []

        worker_utils.handle_result(
            task_key=canonical_task_key,
            data_type=data_type,
            serialized_data=standardized_payload,
            cache_key=cache_key,
            db_rows=None,
            db_model=None,
        )

        if task_key != canonical_task_key:
            TaskRecord.objects.filter(task_key=task_key).update(status="complete", completed_at=timezone.now())

        # Perform heavy DB persistence sequentially AFTER streaming to frontend
        if session_type == "R":
            from api.services.store import store_race_results, store_season_schedule
            from api.services.schedule import get_race_by_round
            from api.models import SeasonSchedule
            store_race_results(int(year), int(round_number), "R", rows)

            try:
                race_info = get_race_by_round(int(year), int(round_number))
                if race_info:
                    existing = SeasonSchedule.objects.filter(year=int(year)).first()
                    races_list = existing.payload.get("races", []) if (existing and existing.payload) else []
                    races_list = [r for r in races_list if r.get("round") != int(round_number)]
                    races_list.append({
                        "round": int(round_number),
                        "name": race_info.get("name", f"Round {round_number}"),
                        "date": race_info.get("date").isoformat() if hasattr(race_info.get("date"), "isoformat") else race_info.get("date"),
                        "location": race_info.get("location"),
                        "country": race_info.get("country", "Unknown"),
                        "event_format": race_info.get("event_format"),
                        "session1": race_info.get("session1"),
                        "session1_date_utc": race_info.get("session1_date_utc").isoformat() if hasattr(race_info.get("session1_date_utc"), "isoformat") else race_info.get("session1_date_utc"),
                        "session2": race_info.get("session2"),
                        "session2_date_utc": race_info.get("session2_date_utc").isoformat() if hasattr(race_info.get("session2_date_utc"), "isoformat") else race_info.get("session2_date_utc"),
                        "session3": race_info.get("session3"),
                        "session3_date_utc": race_info.get("session3_date_utc").isoformat() if hasattr(race_info.get("session3_date_utc"), "isoformat") else race_info.get("session3_date_utc"),
                        "session4": race_info.get("session4"),
                        "session4_date_utc": race_info.get("session4_date_utc").isoformat() if hasattr(race_info.get("session4_date_utc"), "isoformat") else race_info.get("session4_date_utc"),
                        "session5": race_info.get("session5"),
                        "session5_date_utc": race_info.get("session5_date_utc").isoformat() if hasattr(race_info.get("session5_date_utc"), "isoformat") else race_info.get("session5_date_utc"),
                    })
                    races_list.sort(key=lambda r: r.get("round", 0))
                    store_season_schedule(int(year), races_list)
            except Exception:
                pass

        elif session_type == "Q":
            from api.models import QualifyingResultData
            QualifyingResultData.objects.update_or_create(
                year=year,
                round_number=round_number,
                defaults={"payload": {"data": rows}},
            )

        elif session_type in ["S", "SQ"]:
            from api.models import RaceResultData
            RaceResultData.objects.update_or_create(
                year=year,
                round_number=round_number,
                session=session_type,
                defaults={"payload": {"results": rows}},
            )

        elif session_type in ["FP1", "FP2", "FP3"]:
            from api.models import PracticeResultData
            PracticeResultData.objects.update_or_create(
                year=year,
                round_number=round_number,
                session=session_type,
                defaults={"payload": {"results": rows}},
            )

        # Store Driver Laps Analysis for all sessions
        for dc in parsed.all_drivers:
            try:
                store_driver_lap_analysis(
                    year=int(year),
                    round_number=int(round_number),
                    session=session_type,
                    driver_code=dc,
                    laps=parsed.laps_by_driver.get(dc, []),
                    stints=parsed.stints_by_driver.get(dc, []),
                    tyre_strategy=parsed.tyre_by_driver.get(dc, []),
                    pace=parsed.pace_by_driver.get(dc, {}),
                    sectors=parsed.sectors_by_driver.get(dc, {}),
                )
            except Exception:
                pass

        if session_type == "R" and rows:
            try:
                populate_qualifying_results.delay(int(year), int(round_number))
            except Exception:
                pass

    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        error_defaults = {
            "status": "failed",
            "completed_at": timezone.now(),
            "error_message": traceback.format_exc(),
        }
        TaskRecord.objects.filter(task_key__in=[task_key, canonical_task_key]).update(**error_defaults)
        raise
        
    finally:
        cache.delete(f"task_lock:{task_key}")
        try:
            cache.delete(f"task_lock:{canonical_task_key}")
        except Exception:
            pass
