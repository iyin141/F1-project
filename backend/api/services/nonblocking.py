"""
Non-blocking view helper — 3-step cache/DB/stream strategy.

1. Cache hit → return 200 (fast)
2. DB hit → return 200 + backfill cache
3. Cache/DB miss → enqueue Celery task (if not running) + SSE stream
"""

import json
import logging
import os
from typing import Callable, Optional, Any, Dict, Tuple
from rest_framework.response import Response
from rest_framework import status

from api.queue.manager import TaskManager
from api.services.cache_service import set_in_cache, get_cache_ttl
from api.services import streaming
from django.core.cache import cache

logger = logging.getLogger(__name__)


def handle_data_request(
    cache_key: str,
    db_fetch_fn: Callable[[], Any],
    task_fn: Callable,
    task_key: str,
    task_args: Tuple = (),
    task_kwargs: Dict = None,
    cache_ttl: int = None,
):
    """
    Unified entry point for non-blocking data endpoints.

    Step 1: Check Redis cache → return HTTP 200 (JSON) if found.
    Step 2: Call db_fetch_fn() → return HTTP 200 + backfill cache if found.
    Step 3: On miss:
        - If task already pending/running → subscribe and stream result.
        - Otherwise enqueue new task → subscribe and stream result.

    Returns: Response (200 JSON) or StreamingHttpResponse (SSE).
    """
    task_kwargs = task_kwargs or {}

    # ------------------------------------------------------------------
    # STEP 1: Redis cache
    # ------------------------------------------------------------------
    is_test_env = os.getenv("DJANGO_SETTINGS_MODULE") == "f1_project.settings_test"
    cached_raw = None if is_test_env else cache.get(cache_key)

    if cached_raw is not None:
        logger.info("[NonBlocking] Cache hit cache_key=%s task_key=%s", cache_key, task_key)
        try:
            data = json.loads(cached_raw) if isinstance(cached_raw, str) else cached_raw
        except (json.JSONDecodeError, TypeError):
            data = cached_raw
        return Response(data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # STEP 2: DB fallback
    # ------------------------------------------------------------------
    try:
        db_data = db_fetch_fn()
        if db_data is not None:
            logger.info("[NonBlocking] DB hit cache_key=%s task_key=%s", cache_key, task_key)
            _backfill_cache(cache_key, db_data, cache_ttl)
            return Response(db_data, status=status.HTTP_200_OK)
    except Exception as exc:
        logger.warning(
            "[NonBlocking] DB fetch failed (will retry async) cache_key=%s error=%s",
            cache_key, str(exc),
        )

    # ------------------------------------------------------------------
    # STEP 3: Enqueue (if needed) then stream
    # ------------------------------------------------------------------
    existing_task = TaskManager.get_existing_task(task_key)
    if existing_task:
        logger.info("[NonBlocking] Task already in-flight task_key=%s", task_key)
    else:
        logger.info("[NonBlocking] Enqueueing task task_key=%s", task_key)
        TaskManager.enqueue_if_needed(task_key, task_fn, *task_args, **task_kwargs)

    return streaming.stream_task_result_json(task_key)


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
            cache_type = cache_key.split(":")[0]
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
