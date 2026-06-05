"""
Shared utilities for Celery workers to serialize, publish, cache, and persist data.

Implements the standard worker sequence:
1. Serialize output with appropriate serializer
2. Publish result to Redis pub/sub with full payload
3. Cache serialized data with type-specific TTL
4. Persist to DB if applicable (bulk_create for dedicated models)
5. Mark task complete

Usage:
    result_data = extractor.extract()  # Get raw data
    worker_utils.handle_result(
        task_key=task_key,
        data_type="weather",
        serialized_data=serializer.data,
        cache_key=f"weather:{year}:{round}:R",
        db_rows=weather_rows,  # Optional
        db_model=WeatherData,  # Optional
    )
"""
import json
import logging
from typing import Optional, Any, List, Type

from django.core.cache import cache
from django.db import models
from django.utils import timezone

from api.services import pubsub
from api.models import TaskRecord
from api.services.cache import ttl_for

logger = logging.getLogger(__name__)


def handle_result(
    task_key: str,
    data_type: str,
    serialized_data: Any,
    cache_key: str,
    db_rows: Optional[List[dict]] = None,
    db_model: Optional[Type[models.Model]] = None,
    year: Optional[int] = None,
) -> dict:
    """
    Complete result handling for a worker:
    1. Publish to Redis pub/sub
    2. Cache serialized data
    3. Persist to DB if rows provided
    4. Mark TaskRecord complete
    
    Args:
        task_key: Redis channel identifier (e.g., "weather:2024:5")
        data_type: Name of data type (e.g., "weather", "pit_stops")
        serialized_data: Already-serialized response data (dict or list)
        cache_key: Cache key for storage (e.g., "weather:2024:5:R")
        db_rows: List of model instances or dicts to bulk_create (optional)
        db_model: Django model class for bulk_create (required if db_rows provided)
        year: Year for TTL lookup (optional, extracted from cache_key if missing)
    
    Returns:
        dict with keys: published (bool), cached (bool), persisted (bool), task_complete (bool)
    """
    result = {
        "published": False,
        "cached": False,
        "persisted": False,
        "task_complete": False,
    }

    try:
        # Step 1: Publish to pub/sub
        payload = {
            "status": "complete",
            "source": "worker",
            "data_type": data_type,
            "data": serialized_data,
        }
        pubsub.publish_result(task_key, payload)
        result["published"] = True
        logger.debug("worker_utils.published task_key=%s data_type=%s", task_key, data_type)

    except Exception as exc:
        logger.error("worker_utils.publish_failed task_key=%s data_type=%s error=%s", task_key, data_type, exc)
        raise

    try:
        # Step 2: Cache serialized data
        if year is None:
            try:
                parts = cache_key.split(':')
                if len(parts) >= 2:
                    year = int(parts[1])
            except (ValueError, IndexError):
                pass
                
        ttl = ttl_for(data_type, year)
        cache_value = json.dumps(serialized_data) if not isinstance(serialized_data, str) else serialized_data
        cache.set(cache_key, cache_value, ttl)
        result["cached"] = True
        logger.debug("worker_utils.cached task_key=%s cache_key=%s ttl=%s", task_key, cache_key, ttl)

    except Exception as exc:
        logger.warning("worker_utils.cache_failed task_key=%s cache_key=%s error=%s", task_key, cache_key, exc)
        # Non-fatal, continue

    try:
        # Step 3: Persist to DB if rows provided
        if db_rows and db_model:
            if db_rows and isinstance(db_rows[0], dict):
                db_rows = [db_model(**row) for row in db_rows]
            db_model.objects.bulk_create(db_rows, ignore_conflicts=True)
            result["persisted"] = True
            logger.debug("worker_utils.persisted task_key=%s model=%s rows=%d", task_key, db_model.__name__, len(db_rows))

    except Exception as exc:
        logger.warning("worker_utils.persist_failed task_key=%s model=%s error=%s", task_key, db_model.__name__ if db_model else "N/A", exc)
        # Non-fatal, continue

    try:
        # Step 4: Mark task complete
        TaskRecord.objects.filter(task_key=task_key).update(
            status="complete",
            completed_at=timezone.now(),
        )
        result["task_complete"] = True
        logger.debug("worker_utils.task_complete task_key=%s", task_key)

    except Exception as exc:
        logger.warning("worker_utils.task_mark_failed task_key=%s error=%s", task_key, exc)
        # Non-fatal, continue

    return result
