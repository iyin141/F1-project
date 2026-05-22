"""
Cache Service Layer - Pure caching utilities

Handles:
- Standardized cache key generation
- TTL logic based on data freshness
- Lock acquisition/release for task coordination
- Generic get/set operations with caches["default"]

TTL Strategy:
- Historical (>1yr old): 7 days = 604,800s
- Current season completed: 6-12 hrs = 21,600-43,200s (use 12 hrs = 43,200s)
- Current season in-progress: 60-120s (use 120s for safety margin)
- Weather/track status: 5 min = 300s
- Qualifying: 4 hrs = 14,400s
- Standings: 1 hr = 3,600s
- Locks: 90-120s (use 120s)
- Task status: 10 min = 600s
"""

from django.core.cache import caches
from datetime import datetime
from typing import Any, Optional


def build_cache_key(year: int, round_number: int, session: str, data_type: str) -> str:
    """
    Build standardized cache key.
    
    Args:
        year: F1 season year (int)
        round_number: Round number (int)
        session: Session type (e.g., "R", "Q", "P1", "P2", "P3", "S")
        data_type: Data type (e.g., "results", "weather", "incidents", "telemetry")
    
    Returns:
        Standardized cache key: "f1:{year}:{round}:{session}:{data_type}"
    """
    return f"f1:{year}:{round_number}:{session}:{data_type}"


def ttl_for(data_type: str, year: int) -> int:
    """
    Determine TTL in seconds based on data type and data age.
    
    Historical cutoff: data > 1 year old (year < current_year)
    Current season: year == current_year
    
    Args:
        data_type: Type of data (e.g., "weather", "incidents", "standings", 
                   "results", "qualifying", "task_status", "lock")
        year: F1 season year
    
    Returns:
        TTL in seconds
    """
    current_year = datetime.now().year
    is_historical = year < current_year
    
    # Historical data (> 1 year old): 7 days
    if is_historical:
        return 604_800  # 7 days
    
    # Current season data uses shorter TTLs
    data_type_lower = data_type.lower()
    
    # Task status: 10 min
    if data_type_lower == "task_status":
        return 600
    
    # Locks: 120s (conservative for safety)
    if data_type_lower == "lock":
        return 120
    
    # Weather / track status: 5 min
    if data_type_lower in ("weather", "track_status"):
        return 300
    
    # Qualifying: 4 hrs
    if data_type_lower == "qualifying":
        return 14_400
    
    # Standings (driver / constructor): 1 hr
    if data_type_lower in ("standings", "driver_standings", "constructor_standings"):
        return 3_600
    
    # In-progress race/session: 120s
    # This applies to live telemetry, live incidents, etc.
    if data_type_lower in ("incidents", "telemetry", "pit_stops", "lap_data"):
        return 120
    
    # Race results (post-session): 6-12 hrs (use 12 hrs = 43,200s)
    # This applies to finalized results after session completes
    if data_type_lower in ("results", "race_results"):
        return 43_200
    
    # Session data (general): 6-12 hrs
    if data_type_lower == "session_data":
        return 43_200
    
    # Default: 1 hour (safe middle ground)
    return 3_600


def get_from_cache(key: str) -> Optional[Any]:
    """
    Retrieve value from cache.
    
    Args:
        key: Cache key
    
    Returns:
        Cached value or None if not found / expired
    """
    cache = caches["default"]
    return cache.get(key)


def set_in_cache(key: str, data: Any, ttl: int) -> None:
    """
    Store value in cache with TTL.
    
    Args:
        key: Cache key
        data: Value to cache (must be serializable)
        ttl: Time-to-live in seconds
    """
    cache = caches["default"]
    cache.set(key, data, ttl)


def acquire_lock(key: str, ttl: int = 120) -> bool:
    """
    Acquire a distributed lock via cache.
    
    Uses cache.add() which is atomic (only succeeds if key doesn't exist).
    
    Args:
        key: Lock key (typically "lock:{data_key}")
        ttl: Lock TTL in seconds (default 120s)
    
    Returns:
        True if lock acquired, False if already held by another task
    """
    cache = caches["default"]
    lock_key = f"lock:{key}"
    return cache.add(lock_key, True, ttl)


def release_lock(key: str) -> None:
    """
    Release a distributed lock.
    
    Args:
        key: Lock key (must match the key used in acquire_lock)
    """
    cache = caches["default"]
    lock_key = f"lock:{key}"
    cache.delete(lock_key)


def cache_clear_pattern(pattern: str) -> None:
    """
    Clear all cache entries matching a pattern.
    
    Note: LocMemCache (used in tests) and Redis-backed caches support
    iteration. In-memory cache may be inefficient for large datasets.
    
    Args:
        pattern: Pattern to match (e.g., "f1:2024:*" or "lock:*")
    """
    cache = caches["default"]
    # LocMemCache and Redis backends support .delete_many() with pattern matching
    # For Redis, use scan with pattern. For LocMemCache, iterate manually.
    if hasattr(cache, "delete_many"):
        cache.delete_many([k for k in cache._cache.keys() if k.startswith(pattern)])
    elif hasattr(cache, "_cache"):
        # LocMemCache (test environment)
        keys_to_delete = [k for k in cache._cache.keys() if k.startswith(pattern)]
        for k in keys_to_delete:
            cache.delete(k)
