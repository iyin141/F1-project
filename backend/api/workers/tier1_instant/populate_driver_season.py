from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache

from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverSeasonBreakdown
from api.drivers.jolpica_client import (
    resolve_driver_id,
    get_season_driver_map,
    fetch_season_results,
    fetch_season_qualifying,
    fetch_season_sprint,
)
from api.drivers.repository import resolve_driver_metadata
import traceback

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_season(self, task_key: str, driver_code: str, year: int):
    logger.info("event=celery_start task=populate_driver_season task_key=%s driver=%s year=%s", task_key, driver_code, year)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        is_jolpica_id = bool(driver_code and ("_" in driver_code or "-" in driver_code))
        normalized_code = driver_code if is_jolpica_id else (driver_code or "").upper()

        metadata = resolve_driver_metadata(driver_code, year)
        driver_id = metadata.get("driver_id") if metadata else None
        resolved_code = metadata.get("code") if metadata else None

        if not driver_id:
            driver_id = resolve_driver_id(normalized_code, year) if not is_jolpica_id else None

        if not driver_id:
            try:
                season_map_try = get_season_driver_map(year)
                ident = (driver_code or "").strip().lower()
                for did, info in season_map_try.items():
                    name = (info.get('name') or '').lower()
                    if ident and (ident == did.lower() or ident in name.split() or ident == (info.get('code') or '').lower()):
                        driver_id = did
                        break
            except Exception: pass

        if not driver_id:
            result = {
                "driver_code": driver_code,
                "driver_name": None,
                "year": year,
                "total_races": 0,
                "sprint_weekends": 0,
                "races": [],
                "message": "Driver not found"
            }
        else:
            season_map = get_season_driver_map(year)
            driver_info = season_map.get(driver_id, {})
            driver_name = driver_info.get('name')
            canonical_code = resolved_code or ((driver_info.get('code') or None) if driver_info else None)

            driver_id = (driver_id or "").lower()

            races = fetch_season_results(year, driver_id)
            quali = fetch_season_qualifying(year, driver_id)
            
            quali_lookup = {}
            for q in quali:
                round_num = int(q.get('round', 0))
                qr_list = q.get('QualifyingResults', [])
                if qr_list:
                    qr = qr_list[0]
                    quali_lookup[round_num] = {
                        "qualifying_position": int(qr.get('position', 0)) if qr.get('position') else None,
                        "qualifying_time": (qr.get('Q3') or qr.get('Q2') or qr.get('Q1'))
                    }

            sprint_races = fetch_season_sprint(year, driver_id)
            sprint_lookup = {}
            for s in sprint_races:
                round_num = int(s.get('round', 0))
                sr_list = s.get('SprintResults', [])
                if sr_list:
                    sr = sr_list[0]
                    sprint_lookup[round_num] = {
                        "sprint_position": int(sr.get('position', 0)) if sr.get('position') else None,
                        "sprint_points": float(sr.get('points', 0)) if sr.get('points') else None,
                        "sprint_status": sr.get('status'),
                        "sprint_grid": int(sr.get('grid', 0)) if sr.get('grid') else None,
                        "sprint_laps": int(sr.get('laps', 0)) if sr.get('laps') else None,
                        "sprint_fastest_lap": (sr.get('FastestLap', {}).get('rank') == '1')
                    }

            result_races = []
            for race in races:
                round_num = int(race.get('round', 0))
                rr_list = race.get('Results', [])
                if not rr_list: continue
                rr = rr_list[0]

                q_data = quali_lookup.get(round_num, {"qualifying_position": None, "qualifying_time": None})
                s_data = sprint_lookup.get(round_num, {"sprint_position": None, "sprint_points": None, "sprint_status": None, "sprint_grid": None, "sprint_laps": None, "sprint_fastest_lap": None})

                fastest_lap = rr.get('FastestLap', {}).get('rank') == '1'
                pos_str = rr.get('position', '')
                finish_position = int(pos_str) if pos_str.isdigit() else None

                result_races.append({
                    "year": year,
                    "round": round_num,
                    "race_name": race.get('raceName', ''),
                    "location": race.get('Circuit', {}).get('Location', {}).get('locality', ''),
                    "race_date": race.get('date'),
                    "qualifying_position": q_data["qualifying_position"],
                    "qualifying_time": q_data["qualifying_time"],
                    "sprint_position": s_data["sprint_position"],
                    "sprint_points": s_data["sprint_points"],
                    "sprint_status": s_data["sprint_status"],
                    "sprint_grid": s_data["sprint_grid"],
                    "sprint_laps": s_data["sprint_laps"],
                    "sprint_fastest_lap": s_data["sprint_fastest_lap"],
                    "grid_position": int(rr.get('grid', 0)) if rr.get('grid') else None,
                    "finish_position": finish_position,
                    "points": float(rr.get('points', 0)) if rr.get('points') else 0.0,
                    "status": rr.get('status'),
                    "fastest_lap": fastest_lap,
                    "laps_completed": int(rr.get('laps', 0)) if rr.get('laps') else None,
                })

            result = {
                "input": driver_code,
                "driver_id": driver_id,
                "canonical_code": canonical_code,
                "driver_name": driver_name,
                "year": year,
                "total_races": len(result_races),
                "sprint_weekends": len(sprint_lookup),
                "races": result_races,
                "message": None if result_races else "No season data available",
            }

        result["readiness"] = {
            "can_proceed": True, "available_data": ["season_breakdown"], "unavailable_data": [], "message": None, "warnings": []
        }

        # Publish and cache
        cache_key = f"f1:season_breakdown:{driver_code.upper()}:{year}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="season_breakdown",
            serialized_data=result,
            cache_key=cache_key,
            year=year,
        )

        # Async DB Save
        if result.get("races"):
            persist_code = result.get("canonical_code") or (driver_code if len(driver_code) == 3 else driver_code[:3])
            DriverSeasonBreakdown.objects.update_or_create(
                driver_code=persist_code,
                year=int(year),
                defaults={"payload": result}
            )

        logger.info("event=celery_success task=populate_driver_season task_key=%s", task_key)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now(), error_message=traceback.format_exc())
        logger.exception("event=celery_failed task=populate_driver_season task_key=%s", task_key)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
