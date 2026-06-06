from celery import shared_task
import logging
from django.utils import timezone
from django.core.cache import cache
import traceback

from api.services import pubsub, worker_utils
from api.models import TaskRecord

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=0, queue="tier3_medium")
def search_drivers_by_name_task(self, task_key: str, query: str, year: int | None = None):
    logger.info("event=celery_start task=search_drivers_by_name_task task_key=%s query=%s", task_key, query)
    TaskRecord.objects.filter(task_key=task_key).update(status="running", started_at=timezone.now())

    try:
        from django.db.models import Q
        from api.models.drivers import F1Driver

        q_filter = Q(given_name__icontains=query) | Q(family_name__icontains=query) | Q(code__iexact=query) | Q(driver_id__icontains=query)

        drivers = F1Driver.objects.filter(q_filter)
        if year:
            drivers = drivers.filter(seasons__contains=[year])

        drivers = drivers.values('driver_id', 'code', 'given_name', 'family_name', 'nationality', 'number', 'seasons').order_by('family_name', 'given_name')

        results = []
        for d in drivers:
            driver_name = f"{d['given_name']} {d['family_name']}"
            matches = {
                "code": (d['code'] or '').upper() == query.upper() if d['code'] else False,
                "given_name": query.lower() in d['given_name'].lower(),
                "family_name": query.lower() in d['family_name'].lower(),
                "driver_id": query.lower() in d['driver_id'].lower() if d['driver_id'] else False,
            }
            results.append({
                "driver_id": d['driver_id'],
                "driver_code": d['code'],
                "driver_name": driver_name,
                "nationality": d['nationality'],
                "number": d['number'],
                "seasons": d['seasons'],
                "matches": matches,
            })

        payload = {
            "query": query,
            "year": year,
            "count": len(results),
            "results": results,
            "message": None if results else ("Driver database not yet synced." if not F1Driver.objects.exists() else None),
        }

        # Publish and cache
        worker_utils.handle_result(
            task_key=task_key,
            data_type="driver_search",
            serialized_data=payload,
            cache_key=task_key,
            year=year or 2025,
        )

        logger.info("event=celery_success task=search_drivers_by_name_task task_key=%s query=%s", task_key, query)
    except Exception as exc:
        pubsub.publish_error(task_key, str(exc))
        TaskRecord.objects.filter(task_key=task_key).update(status="failed", completed_at=timezone.now(), error_message=traceback.format_exc())
        logger.exception("event=celery_failed task=search_drivers_by_name_task task_key=%s query=%s", task_key, query)
        raise
    finally:
        cache.delete(f"task_lock:{task_key}")
