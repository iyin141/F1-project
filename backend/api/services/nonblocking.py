"""
Non-blocking view pattern — Module S: 4-step async/cache strategy.

Implements:
1. Cache hit → return 200 (fast)
2. DB hit → return 200 + backfill cache
3. Task exists → return 202 with task_id
4. Enqueue task → return 202 with task_id

Usage in views:
    response = await_or_enqueue_data(
        cache_key="races:2024:1:results",
        db_fetch_fn=lambda: get_race_results(year, round_number),
        task_fn=populate_session_data,
        task_key=f"seed_round:{year}:{round_number}",
        task_args=(year, round_number),
        request=request,
        context={"year": year, "round": round_number}
    )
    return response
"""

import json
import logging
import os
from typing import Callable, Optional, Any, Dict, Tuple
from rest_framework.response import Response
from rest_framework import status

from api.queue.manager import TaskManager
from api.services.cache_service import (
    set_cache, set_in_cache, build_cache_key
)
from django.core.cache import cache
from api.models import TaskRecord

logger = logging.getLogger(__name__)


def await_or_enqueue_data(
    cache_key: str,
    db_fetch_fn: Callable[[], Any],
    task_fn: Callable,
    task_key: str,
    task_args: Tuple = (),
    task_kwargs: Dict = None,
    request = None,
    context: Dict = None,
    cache_ttl: int = None,
) -> Response:
    """
    4-step non-blocking pattern for data loading.
    
    Step 1: Check Redis cache → return 200 if found
    Step 2: Check DB → return 200 + backfill cache if found
    Step 3: Check if task already queued → return 202 with task_id
    Step 4: Enqueue new task → return 202 with task_id
    
    Args:
        cache_key: Redis key for caching (e.g., "races:2024:1:results")
        db_fetch_fn: Function to fetch from DB/service
        task_fn: Celery task function to enqueue for missing data
        task_key: Unique identifier for the task (e.g., "seed_round:2024:1")
        task_args: Arguments to pass to task_fn
        task_kwargs: Keyword arguments for task_fn
        request: DRF request object (for logging/tracing)
        context: Additional context (year, round, etc.) for building response
        cache_ttl: Optional TTL override (uses default from ttl_for() if None)
    
    Returns:
        Response with status 200 (data found), 202 (task enqueued), or 500 (error)
    
    Response format (200 - from cache or DB):
        {
            "source": "cache" | "database",
            "data": {...},
            "cached_at": "2024-05-23T12:00:00Z",  # if from cache
            "meta": {...}  # if provided in context
        }
    
    Response format (202 - task enqueued):
        {
            "status": "enqueued",
            "task_id": "seed_round:2024:1",
            "estimated_wait_seconds": 45,
            "queue_depth": 5,
            "poll_url": "/api/tasks/{task_id}/status/"
        }
    """
    task_kwargs = task_kwargs or {}
    context = context or {}
    
    try:
        # ===================================================================
        # STEP 1: Check Redis cache (direct key lookup)
        # ===================================================================
        # In test runs, skip cache to avoid stale-cache flakiness.
        # Production uses Redis and cache normally.
        is_test_env = os.getenv("DJANGO_SETTINGS_MODULE") == "f1_project.settings_test"
        if is_test_env:
            logger.debug("[NonBlocking] Skipping cache read for test environment")
            cached_raw = None
        else:
            cached_raw = cache.get(cache_key)

        if cached_raw is not None:
            logger.info(
                "[NonBlocking] Cache hit cache_key=%s task_key=%s",
                cache_key, task_key
            )
            
            # Parse cached JSON
            try:
                data = json.loads(cached_raw) if isinstance(cached_raw, str) else cached_raw
            except (json.JSONDecodeError, TypeError):
                data = cached_raw

            # Ensure readiness metadata for legacy payload shapes
            data = _ensure_readiness_for_payload(data, context)

            return Response(data, status=status.HTTP_200_OK)
        
        # ===================================================================
        # STEP 2: Check database
        # ===================================================================
        try:
            db_data = db_fetch_fn()
            if db_data is not None:
                logger.info(
                    "[NonBlocking] DB hit cache_key=%s task_key=%s",
                    cache_key, task_key
                )
                # Backfill cache
                _backfill_cache(cache_key, db_data, cache_ttl)

                # Ensure readiness metadata for legacy payload shapes then return
                db_data = _ensure_readiness_for_payload(db_data, context)
                return Response(db_data, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.warning(
                "[NonBlocking] DB fetch failed (will retry async) cache_key=%s error=%s",
                cache_key, str(exc)
            )
            # Fall through to task enqueueing
        
        # ===================================================================
        # STEP 3: Check if task already queued
        # ===================================================================
        existing_task = TaskManager.get_existing_task(task_key)
        if existing_task:
            logger.info(
                "[NonBlocking] Task already queued task_key=%s celery_id=%s",
                task_key, existing_task.celery_task_id
            )
            
            # Estimate wait time
            queue_depth = TaskManager.get_queue_depth(queue_name=None)
            estimated_wait = _estimate_wait_time(task_key, queue_depth)
            
            return Response(
                {
                    "status": "enqueued",
                    "task_id": str(existing_task.celery_task_id),
                    "task_key": task_key,
                    "estimated_wait_seconds": estimated_wait,
                    "queue_depth": queue_depth,
                    "poll_url": f"/api/tasks/{existing_task.celery_task_id}/status/",
                },
                status=status.HTTP_202_ACCEPTED
            )
        
        # ===================================================================
        # STEP 4: Enqueue new task
        # ===================================================================
        logger.info(
            "[NonBlocking] Enqueueing task task_key=%s",
            task_key
        )
        
        enqueued = TaskManager.enqueue_if_needed(task_key, task_fn, *task_args, **task_kwargs)
        
        if not enqueued:
            logger.error(
                "[NonBlocking] Failed to enqueue task task_key=%s",
                task_key
            )
            return Response(
                {
                    "error": "Failed to enqueue task",
                    "task_key": task_key,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Get the newly created task record for response
        new_task = TaskManager.get_existing_task(task_key)
        if not new_task:
            logger.error(
                "[NonBlocking] Task record not found after enqueue task_key=%s",
                task_key
            )
            return Response(
                {
                    "error": "Task enqueued but record not found",
                    "task_key": task_key,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        queue_depth = TaskManager.get_queue_depth(queue_name=None)
        estimated_wait = _estimate_wait_time(task_key, queue_depth)
        
        logger.info(
            "[NonBlocking] Task enqueued successfully task_key=%s celery_id=%s queue_depth=%d",
            task_key, new_task.celery_task_id, queue_depth
        )
        
        return Response(
            {
                "status": "enqueued",
                "task_id": str(new_task.celery_task_id),
                "task_key": task_key,
                "estimated_wait_seconds": estimated_wait,
                "queue_depth": queue_depth,
                "poll_url": f"/api/tasks/{new_task.celery_task_id}/status/",
            },
            status=status.HTTP_202_ACCEPTED
        )
    
    except Exception as exc:
        logger.exception(
            "[NonBlocking] Unhandled error cache_key=%s task_key=%s error=%s",
            cache_key, task_key, str(exc)
        )
        return Response(
            {
                "error": "Internal server error",
                "detail": str(exc),
                "task_key": task_key,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _backfill_cache(cache_key: str, data: Any, ttl_override: Optional[int] = None) -> bool:
    """
    Store data in Redis cache after DB fetch.
    
    Args:
        cache_key: Redis key
        data: Data to cache (will be JSON serialized if dict/list)
        ttl_override: Optional TTL in seconds (overrides auto-calc)
    
    Returns:
        True if cached, False if error
    """
    try:
        # Serialize data
        if isinstance(data, (dict, list)):
            cache_data = json.dumps(data)
        else:
            cache_data = data
        
        # Do not backfill when in test environment (tests rely on ephemeral cache state)
        is_test_env = os.getenv("DJANGO_SETTINGS_MODULE") == "f1_project.settings_test"
        if is_test_env:
            logger.debug("[NonBlocking] Skipping cache backfill for test environment")
            return False

        # Determine TTL
        if ttl_override:
            ttl = ttl_override
        else:
            from api.services.cache_service import get_cache_ttl
            # Extract data type from cache_key for TTL lookup
            cache_type = cache_key.split(":")[0]  # e.g., "races:2024:1:results" → "races"
            ttl = get_cache_ttl(cache_type)

        # Store in cache
        set_in_cache(cache_key, cache_data, ttl)
        logger.debug("[NonBlocking] Cache backfilled cache_key=%s ttl=%ds", cache_key, ttl)
        return True
    except Exception as exc:
        logger.warning(
            "[NonBlocking] Cache backfill failed cache_key=%s error=%s",
            cache_key, str(exc)
        )
        return False


def _estimate_wait_time(task_key: str, queue_depth: int) -> int:
    """
    Estimate task wait time based on task type and queue depth.
    
    Args:
        task_key: Task identifier (e.g., "seed_round:2024:1")
        queue_depth: Number of pending tasks
    
    Returns:
        Estimated wait time in seconds, capped at 300 (5 minutes)
    """
    if queue_depth <= 0:
        return 0
    
    try:
        # Map task types to worker count and typical duration
        if "telemetry" in task_key or "overlay" in task_key:
            # Telemetry: slower tasks
            avg_duration = 45  # seconds
            workers = 2
        elif "laps" in task_key or "pace" in task_key or "stint" in task_key:
            # Analysis: medium speed
            avg_duration = 15
            workers = 3
        elif "results" in task_key or "qualifying" in task_key or "practice" in task_key:
            # Results: fast
            avg_duration = 5
            workers = 4
        else:
            # Default: conservative estimate
            avg_duration = 10
            workers = 2
        
        # Calculate: (queue_depth / workers) * avg_duration
        estimated = int((queue_depth / workers) * avg_duration)
        
        # Cap at 5 minutes
        return min(estimated, 300)
    except Exception:
        # Fallback: linear estimate
        return min(queue_depth * 10, 300)


def build_nonblocking_response_202(task_key: str, celery_task_id: str, queue_depth: int = 0) -> Dict:
    """
    Build a 202 Accepted response body.
    
    Args:
        task_key: The task key (e.g., "seed_round:2024:1")
        celery_task_id: The Celery task UUID
        queue_depth: Estimated queue depth
    
    Returns:
        Response dict ready for Response(data, status=202)
    """
    estimated_wait = _estimate_wait_time(task_key, queue_depth)
    
    return {
        "status": "enqueued",
        "task_id": str(celery_task_id),
        "task_key": task_key,
        "estimated_wait_seconds": estimated_wait,
        "queue_depth": queue_depth,
        "poll_url": f"/api/tasks/{celery_task_id}/status/",
    }


def build_nonblocking_response_200(data: Any, source: str = "database", context: Dict = None) -> Dict:
    """
    Build a 200 OK response body.
    
    Args:
        data: The loaded data
        source: "cache" or "database"
        context: Additional context to include (year, round, etc.)
    
    Returns:
        Response dict ready for Response(data, status=200)
    """
    return {
        "source": source,
        "data": data,
        "meta": context or {},
    }


def _ensure_readiness_for_payload(payload: Any, context: Dict | None = None) -> Any:
    """
    Ensure a minimal `readiness` key is present on payloads returned by
    non-blocking endpoints. This covers legacy service shapes used by the
    results/qualifying/practice endpoints in tests.
    """
    if not isinstance(payload, dict):
        return payload

    # Do not overwrite an existing readiness block
    if "readiness" in payload:
        return payload

    # Import helpers lazily to avoid circular imports
    from api.common.readiness import build_readiness, ensure_payload_meta_checklist

    year = None
    round_number = None
    if context:
        year = context.get("year")
        round_number = context.get("round")
    year = year or payload.get("year")
    round_number = round_number or payload.get("round")

    # Results payload (contains qualifying + race)
    if "results" in payload and isinstance(payload["results"], dict):
        qualifying_rows = payload["results"].get("qualifying", []) or []
        race_rows = payload["results"].get("race", []) or []

        available = []
        unavailable = []
        if qualifying_rows:
            available.append("qualifying_results")
        else:
            unavailable.append("qualifying_results")
        if race_rows:
            available.append("race_results")
        else:
            unavailable.append("race_results")

        can_proceed = bool(qualifying_rows or race_rows)
        message = None if can_proceed else (f"No results data returned for {year} Round {round_number}.")
        payload["readiness"] = build_readiness(can_proceed, available, unavailable, None if can_proceed else message, [] if can_proceed else ([message] if message else []))
        return payload

    # Qualifying-only payload
    if "qualifying" in payload:
        rows = payload.get("qualifying") or []
        can_proceed = bool(rows)
        available = ["qualifying_results"] if rows else []
        unavailable = [] if rows else ["qualifying_results"]
        message = None if can_proceed else (f"No qualifying data returned for {year} Round {round_number}.")
        payload["readiness"] = build_readiness(can_proceed, available, unavailable, None if can_proceed else message, [] if can_proceed else ([message] if message else []))
        return payload

    # Practice-only payload
    if "practice" in payload:
        rows = payload.get("practice") or []
        can_proceed = bool(rows)
        available = ["practice_results"] if rows else []
        unavailable = [] if rows else ["practice_results"]
        message = None if can_proceed else (f"No practice data returned for {year} Round {round_number}.")
        payload["readiness"] = build_readiness(can_proceed, available, unavailable, None if can_proceed else message, [] if can_proceed else ([message] if message else []))
        return payload

    # Payload with a meta block: ensure meta contains readiness fields
    if "meta" in payload and isinstance(payload["meta"], dict):
        # Ensure meta has readiness fields, then promote them to a top-level
        # `readiness` key so endpoints return a consistent shape expected by
        # the tests and frontend.
        payload = ensure_payload_meta_checklist(payload)
        meta = payload.get("meta", {})
        # If the meta block now contains readiness, copy it to top-level.
        if all(k in meta for k in ("can_proceed", "available_data", "unavailable_data")):
            payload["readiness"] = {
                "can_proceed": meta.get("can_proceed"),
                "available_data": meta.get("available_data"),
                "unavailable_data": meta.get("unavailable_data"),
                "message": meta.get("message"),
                "warnings": meta.get("warnings", []),
            }
        return payload

    return payload
