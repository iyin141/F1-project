"""
Cache service — Phase 4, Problem #2: Write-through Redis cache pattern.

Implements the read priority chain:
1. Redis cache → return immediately (sub-10ms)
2. PostgreSQL DB → backfill Redis, return (100ms)
3. Both miss + no load lock → enqueue Celery task + set load lock, return 202
4. Both miss + load lock exists → return 202 with existing task ID

Also handles session LRU registry for in-process session object management.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Any, Callable
from datetime import datetime

from django.core.cache import cache, caches
from django.utils.timezone import now as django_now

logger = logging.getLogger(__name__)


# ============================================================================
# CACHE KEY BUILDERS
# ============================================================================

def build_cache_key(data_type: str, year: int, round_number: int, session: str) -> str:
    """Build cache key for session-based data."""
    return f"session:{year}:{round_number}:{session}:{data_type}"


def build_load_lock_key(data_type: str, year: int, round_number: int, session: str) -> str:
    """Build cache key for in-flight load lock (SETNX)."""
    return f"session_loading:{year}:{round_number}:{session}:{data_type}"


def build_task_status_key(task_id: str) -> str:
    """Build cache key for task status polling."""
    return f"task_status:{task_id}"


def build_session_lru_key(worker_type: str) -> str:
    """Build Redis sorted set key for session LRU registry."""
    return f"session_lru_registry:{worker_type}"


# ============================================================================
# CACHE READ CHAIN
# ============================================================================

def get_from_cache(
    data_type: str,
    year: int,
    round_number: int,
    session: str,
    model_queryset: Optional[Any] = None,
) -> tuple[Optional[Any], str]:
    """
    Read priority chain: Redis → DB → None.
    
    Returns: (data, source) where source is "redis", "db", or "miss"
    
    Args:
        data_type: Type of data (e.g., "standings", "weather", "telemetry")
        year, round_number, session: Session identifiers
        model_queryset: Optional Django ORM queryset to fetch from DB if cache miss
        
    Example:
        data, source = get_from_cache("standings", 2026, 4, "R", Driver.objects.all())
        if source == "redis":
            return Response(data, status=200)  # Sub-10ms hit
        elif source == "db":
            return Response(data, status=200)  # Backfilled from DB
        else:
            # Cache miss — check for load lock and enqueue task
    """
    key = build_cache_key(data_type, year, round_number, session)
    
    # Step 1: Check Redis cache
    try:
        cached = cache.get(key)
        if cached is not None:
            logger.info(
                "[CacheChain] Redis hit data_type=%s year=%s round=%s session=%s",
                data_type, year, round_number, session,
            )
            # Deserialize if stored as JSON string
            if isinstance(cached, str):
                try:
                    return json.loads(cached), "redis"
                except (json.JSONDecodeError, TypeError):
                    return cached, "redis"
            return cached, "redis"
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=get key=%s error=%s", key, exc)
        # Fall through to DB check
    
    # Step 2: Check PostgreSQL DB
    if model_queryset is not None:
        try:
            db_data = model_queryset
            if hasattr(db_data, 'first'):
                db_data = db_data.first()
            
            if db_data is not None:
                # Serialize to JSON and store in cache
                if hasattr(db_data, 'to_representation'):
                    serialized = db_data.to_representation()
                else:
                    serialized = db_data
                
                cache.set(key, json.dumps(serialized) if not isinstance(serialized, str) else serialized, timeout=300)
                logger.info(
                    "[CacheChain] DB hit (backfilled Redis) data_type=%s year=%s round=%s session=%s",
                    data_type, year, round_number, session,
                )
                return serialized, "db"
        except Exception as exc:
            logger.warning("[CacheChain] DB lookup failed data_type=%s error=%s", data_type, exc)
            # Fall through to cache miss
    
    # Step 3: Cache miss — no data in Redis or DB
    logger.info(
        "[CacheChain] Cache miss data_type=%s year=%s round=%s session=%s",
        data_type, year, round_number, session,
    )
    return None, "miss"


# ============================================================================
# CACHE WRITE (DIRECT KEY)
# ============================================================================

def set_in_cache(cache_key: str, data: Any, timeout: int = 300) -> bool:
    """
    Set cache by key directly (generic wrapper for any cache_key).
    
    Used by nonblocking.py and other modules that work with cache keys directly.
    
    Args:
        cache_key: Full cache key (e.g., "session:2024:1:R:standings")
        data: Data to cache (serialized as JSON if not string)
        timeout: TTL in seconds (default 300)
    
    Returns:
        True on success, False on error
    """
    try:
        if isinstance(data, str):
            cache.set(cache_key, data, timeout=timeout)
        else:
            cache.set(cache_key, json.dumps(data), timeout=timeout)
        
        logger.debug("[CacheWrite] Direct key cached key=%s ttl=%ds", cache_key, timeout)
        return True
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=set key=%s error=%s", cache_key, exc)
        return False


def set_cache(
    data_type: str,
    year: int,
    round_number: int,
    session: str,
    data: Any,
    timeout: int = 300,
) -> bool:
    """
    Backfill Redis cache after task completion.
    
    Returns True on success, False on error.
    """
    key = build_cache_key(data_type, year, round_number, session)
    try:
        # Serialize if not already a string
        if isinstance(data, str):
            cache.set(key, data, timeout=timeout)
        else:
            cache.set(key, json.dumps(data), timeout=timeout)
        
        logger.info(
            "[CacheWrite] Data cached data_type=%s year=%s round=%s session=%s ttl=%ds",
            data_type, year, round_number, session, timeout,
        )
        return True
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=set key=%s error=%s", key, exc)
        return False


# ============================================================================
# IN-FLIGHT LOAD LOCKS (SETNX DEDUPLICATION)
# ============================================================================

def check_load_lock(
    data_type: str,
    year: int,
    round_number: int,
    session: str,
) -> Optional[str]:
    """
    Check if a load is already in progress (SETNX lock exists).
    
    Returns lock value (usually existing task_id) if locked, None if not locked.
    """
    key = build_load_lock_key(data_type, year, round_number, session)
    try:
        lock_value = cache.get(key)
        if lock_value is not None:
            logger.info(
                "[LoadLock] Lock already held data_type=%s year=%s round=%s session=%s existing_task=%s",
                data_type, year, round_number, session, lock_value,
            )
            return lock_value
        return None
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=get key=%s error=%s", key, exc)
        return None


def set_load_lock(
    data_type: str,
    year: int,
    round_number: int,
    session: str,
    task_id: str,
    ttl: int = 120,
) -> bool:
    """
    Acquire an in-flight load lock via SETNX.
    
    Returns True if lock acquired, False if already locked.
    
    Args:
        task_id: Celery task ID to store in the lock
        ttl: Lock TTL in seconds (must exceed max load time for data type)
    """
    key = build_load_lock_key(data_type, year, round_number, session)
    try:
        # SETNX: set only if key doesn't exist
        acquired = cache.set(key, task_id, timeout=ttl, nx=True)
        if acquired:
            logger.info(
                "[LoadLock] Lock acquired data_type=%s year=%s round=%s session=%s task_id=%s ttl=%ds",
                data_type, year, round_number, session, task_id, ttl,
            )
        else:
            logger.info(
                "[LoadLock] Lock already held data_type=%s year=%s round=%s session=%s",
                data_type, year, round_number, session,
            )
        return acquired
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=lock key=%s error=%s", key, exc)
        return False


def release_load_lock(
    data_type: str,
    year: int,
    round_number: int,
    session: str,
) -> bool:
    """Release an in-flight load lock immediately (don't wait for TTL)."""
    key = build_load_lock_key(data_type, year, round_number, session)
    try:
        cache.delete(key)
        logger.info(
            "[LoadLock] Lock released data_type=%s year=%s round=%s session=%s",
            data_type, year, round_number, session,
        )
        return True
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=delete key=%s error=%s", key, exc)
        return False


# ============================================================================
# TASK STATUS POLLING
# ============================================================================

def set_task_status(task_id: str, status: str, timeout: int = 600) -> bool:
    """
    Set task status for polling.
    
    Status values: "queued", "loading", "complete", "failed"
    """
    key = build_task_status_key(task_id)
    try:
        cache.set(key, status, timeout=timeout)
        logger.debug("[TaskStatus] Status set task_id=%s status=%s ttl=%ds", task_id, status, timeout)
        return True
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=set key=%s error=%s", key, exc)
        return False


def get_task_status(task_id: str) -> Optional[str]:
    """Get task status for polling."""
    key = build_task_status_key(task_id)
    try:
        status = cache.get(key)
        return status
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=get key=%s error=%s", key, exc)
        return None


def clear_task_status(task_id: str) -> bool:
    """Clear task status from cache (used during cleanup)."""
    key = build_task_status_key(task_id)
    try:
        cache.delete(key)
        logger.debug("[TaskStatus] Status cleared task_id=%s", task_id)
        return True
    except Exception as exc:
        logger.warning("event=cache_unavailable operation=delete key=%s error=%s", key, exc)
        return False


# ============================================================================
# SESSION LRU REGISTRY (for in-process session object tracking)
# ============================================================================

def register_session_lru(worker_type: str, session_key: str, timestamp: float) -> bool:
    """
    Register or update a session in the LRU registry.
    
    Uses Redis sorted set with Unix timestamp as score for LRU ordering.
    """
    registry_key = build_session_lru_key(worker_type)
    try:
        cache.zset(registry_key, {session_key: timestamp})
        logger.debug("[SessionLRU] Session registered worker_type=%s key=%s", worker_type, session_key)
        return True
    except Exception as exc:
        # django-redis may not support zset or Redis could be unavailable
        logger.warning("event=cache_unavailable operation=zadd key=%s error=%s", registry_key, exc)
        return False


def get_session_lru_count(worker_type: str) -> int:
    """Get number of sessions in the LRU registry."""
    registry_key = build_session_lru_key(worker_type)
    try:
        # Note: This requires custom redis access; django-redis doesn't expose ZCARD directly
        # For now, return 0 and log a note. This can be improved with raw Redis client.
        logger.debug("[SessionLRU] ZCARD not exposed in django-redis; returning 0")
        return 0
    except Exception:
        return 0


def evict_oldest_session_lru(worker_type: str) -> Optional[str]:
    """
    Evict the least recently used (oldest) session from the registry.
    
    Returns the evicted session key or None.
    """
    registry_key = build_session_lru_key(worker_type)
    try:
        # Would use ZRANGE + ZREM here with raw Redis client
        logger.debug("[SessionLRU] ZRANGE/ZREM not exposed in django-redis; skipping eviction")
        return None
    except Exception:
        return None


# ============================================================================
# TTL LADDER — standardised per data type (Phase 4 Problem #18)
# ============================================================================

def get_cache_ttl(data_type: str, is_completed: bool = False) -> int:
    """
    Get cache TTL in seconds for a data type.
    
    Args:
        data_type: Type of data (e.g., "standings", "weather", "telemetry_trace")
        is_completed: Whether the data is final (completed race) or live
    """
    if not is_completed:
        # Live, in-progress race — short TTL
        return 60  # 1 minute — updates during live session
    
    # Completed race — longer TTL
    ttl_map = {
        "standings": 3600,  # 1 hour — updates only after each race
        "weather": 300,  # 5 min — changes frequently mid-session
        "incidents": 300,  # 5 min
        "pit_stops": 600,  # 10 min
        "positions": 300,  # 5 min
        "drs": 300,  # 5 min
        "track_status": 300,  # 5 min
        "laps": 600,  # 10 min — lap times can be updated/corrected
        "pace": 600,  # 10 min
        "stints": 600,  # 10 min
        "sectors": 600,  # 10 min
        "tyre_strategy": 600,  # 10 min
        "results": 14400,  # 4 hours — final after session ends
        "qualifying": 14400,  # 4 hours
        "telemetry_trace": 1800,  # 30 min — short TTL (burst-accessed then cold)
        "telemetry_overlay": 1800,  # 30 min
        "telemetry_compare": 3600,  # 1 hour
        "telemetry_grid": 7200,  # 2 hours — grid summary more expensive
    }
    return ttl_map.get(data_type, 3600)  # Default 1 hour


def get_load_lock_ttl(data_type: str) -> int:
    """
    Get in-flight load lock TTL in seconds (must exceed max load time for data type).
    
    Matches TASK_TIER_MAP from backend/api/queue/manager.py
    """
    tier_map = {
        # Tier 1: Instant — 30s lock TTL
        "standings": 30,
        "constructor_standings": 30,
        "driver_career": 30,
        "driver_season": 30,
        "schedule": 30,
        
        # Tier 2: Fast — 60s lock TTL
        "race_results": 60,
        "session_data": 60,
        "results": 60,
        "qualifying": 60,
        "weather": 60,
        "incidents": 60,
        "pit_stops": 60,
        "track_status": 60,
        
        # Tier 3: Medium — 90s lock TTL
        "laps": 90,
        "pace": 90,
        "stints": 90,
        "sectors": 90,
        "positions": 90,
        "drs": 90,
        "tyre_strategy": 90,
        
        # Tier 4: Telemetry — 180s lock TTL
        "telemetry": 180,
        "telemetry_trace": 180,
        "telemetry_overlay": 180,
        "telemetry_summary": 180,
        "telemetry_grid": 180,
    }
    return tier_map.get(data_type, 90)  # Default 90s (tier 3)
