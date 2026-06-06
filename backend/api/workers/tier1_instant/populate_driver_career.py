from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache

from api.services import pubsub
from api.services import worker_utils
from api.models import TaskRecord, DriverCareer
from api.drivers.jolpica_client import resolve_driver_id, fetch_all_driver_results
from api.drivers.repository import resolve_driver_metadata
from api.drivers.services.champions_sync_service import ChampionsSyncService
import traceback

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier1_instant")
def populate_driver_career(self, task_key: str, driver_code: str):
    logger.info("event=celery_start task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        is_jolpica_id = bool(driver_code and ("_" in driver_code or "-" in driver_code or len(driver_code) > 3))
        normalized_code = driver_code if is_jolpica_id else (driver_code or "").upper()

        metadata = resolve_driver_metadata(driver_code)
        driver_id = metadata.get("driver_id") if metadata else None
        resolved_code = metadata.get("code") if metadata else None

        if not driver_id:
            driver_id = resolve_driver_id(normalized_code) if not is_jolpica_id else None
            
        if not driver_id:
            result = {
                "input": driver_code,
                "driver_id": None,
                "canonical_code": None,
                "driver_name": None,
                "nationality": None,
                "career": [],
                "career_totals": {"total_wins": 0, "total_podiums": 0},
                "message": "Driver not found in Jolpica",
            }
        else:
            wins = 0
            podiums = 0
            by_year = {}
            driver_name = None
            nationality = None

            races = fetch_all_driver_results(driver_id)
            for race in races:
                year = int(race.get('season', 0))
                if not year: continue
                results = race.get('Results', [])
                if not results: continue
                result_info = results[0]

                pos_str = result_info.get('position', '')
                if not pos_str or not str(pos_str).lstrip('-').isdigit(): continue
                try: position = int(pos_str)
                except Exception: continue

                if not driver_name:
                    driver_info = result_info.get('Driver', {})
                    driver_name = f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip()
                    nationality = driver_info.get('nationality')

                if year not in by_year:
                    by_year[year] = {'wins': 0, 'podiums': 0, 'races': 0, 'champion': False}

                by_year[year]['races'] += 1
                if position == 1:
                    wins += 1; podiums += 1; by_year[year]['wins'] += 1; by_year[year]['podiums'] += 1
                elif position in (2, 3):
                    podiums += 1; by_year[year]['podiums'] += 1

            championships = 0
            championship_years = ChampionsSyncService().get_championship_years(driver_id)
            for year in by_year:
                if year in championship_years:
                    by_year[year]['champion'] = True
                    championships += 1

            career_data = sorted(
                [{"year": y, "races": s["races"], "wins": s["wins"], "podiums": s["podiums"], "champion": s["champion"]} for y, s in by_year.items()],
                key=lambda x: x["year"], reverse=True
            )

            canonical_code = resolved_code

            result = {
                "input": driver_code,
                "driver_id": driver_id,
                "canonical_code": canonical_code,
                "driver_name": driver_name,
                "nationality": nationality,
                "career": career_data,
                "career_totals": {
                    "total_wins": wins,
                    "total_podiums": podiums,
                    "championships": championships,
                },
                "message": None if career_data else "No career data available",
            }

        # Add readiness
        result["readiness"] = {
            "can_proceed": True, "available_data": ["career"], "unavailable_data": [], "message": None, "warnings": []
        }

        # Publish and cache
        cache_key = f"f1:career:{driver_code.upper()}"
        worker_utils.handle_result(
            task_key=task_key,
            data_type="driver_career",
            serialized_data=result,
            cache_key=cache_key,
            year=2020,  # default
        )

        # Async DB Save
        if result.get("career"):
            persist_code = result.get("canonical_code") or (driver_code if len(driver_code) == 3 else driver_code[:3])
            DriverCareer.objects.update_or_create(
                driver_code=persist_code,
                defaults={"payload": result}
            )

        logger.info("event=celery_success task=populate_driver_career task_key=%s driver=%s", task_key, driver_code)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now(), error_message=traceback.format_exc())
        logger.exception("event=celery_failed task=populate_driver_career task_key=%s", task_key)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
