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

    return streaming.stream_task_result(task_key)


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
