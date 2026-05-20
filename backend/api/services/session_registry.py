"""
Session LRU Registry — Phase 4, Problem #18: Track in-process session objects.

Maintains a Redis sorted set per worker type tracking which session objects
are cached in process memory, scored by access time for LRU eviction.

This is separate from the on-disk FastF1 session object cache. It tracks
which sessions have been loaded into memory on each worker.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Set

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client for registry operations (main cache Redis 1)."""
    try:
        redis_url = settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else "redis://localhost:6379"
        # Connect to db=1 (main app cache)
        return redis.from_url(f"{redis_url}/1", decode_responses=True)
    except Exception as exc:
        logger.warning("[SessionRegistry] Redis connection failed: %s", exc)
        return None


def build_registry_key(worker_type: str) -> str:
    """Build Redis sorted set key for session registry."""
    return f"session_lru_registry:{worker_type}"


def register_session(worker_type: str, session_key: str) -> bool:
    """
    Register or update a session in the LRU registry.
    
    Uses Redis sorted set with Unix timestamp as score for LRU ordering.
    Call this every time a session is accessed to keep the score current.
    
    Returns True on success, False on error.
    """
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return False
        
        registry_key = build_registry_key(worker_type)
        timestamp = time.time()
        
        # ZADD: add or update member with new score (timestamp)
        redis_client.zadd(registry_key, {session_key: timestamp})
        logger.debug("[SessionRegistry] Session registered worker_type=%s session_key=%s", worker_type, session_key)
        return True
    except Exception as exc:
        logger.warning("[SessionRegistry] Register failed worker_type=%s error=%s", worker_type, exc)
        return False


def get_registry_count(worker_type: str) -> int:
    """Get number of sessions currently in the registry."""
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return 0
        
        registry_key = build_registry_key(worker_type)
        count = redis_client.zcard(registry_key)
        return count or 0
    except Exception as exc:
        logger.warning("[SessionRegistry] Count failed worker_type=%s error=%s", worker_type, exc)
        return 0


def get_lru_sessions(worker_type: str, count: int = 5) -> list[str]:
    """
    Get the N oldest (least recently used) sessions from the registry.
    
    Returns list of session keys, ordered from oldest to newest.
    """
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return []
        
        registry_key = build_registry_key(worker_type)
        # ZRANGE with BYSCORE: get by score (timestamp) in ascending order
        # Start from -inf (oldest) up to current time, limit to 'count'
        lru_keys = redis_client.zrange(registry_key, 0, count - 1)  # Get first N (oldest)
        return lru_keys if lru_keys else []
    except Exception as exc:
        logger.warning("[SessionRegistry] Get LRU failed worker_type=%s error=%s", worker_type, exc)
        return []


def evict_session(worker_type: str, session_key: str) -> bool:
    """
    Remove a session from the registry (call when evicting from in-process cache).
    
    Returns True if session was in registry and removed, False otherwise.
    """
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return False
        
        registry_key = build_registry_key(worker_type)
        removed = redis_client.zrem(registry_key, session_key)
        if removed:
            logger.info("[SessionRegistry] Session evicted worker_type=%s session_key=%s", worker_type, session_key)
        return bool(removed)
    except Exception as exc:
        logger.warning("[SessionRegistry] Evict failed worker_type=%s session_key=%s error=%s", worker_type, session_key, exc)
        return False


def clear_registry(worker_type: str) -> bool:
    """Clear all entries from a worker type's registry."""
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return False
        
        registry_key = build_registry_key(worker_type)
        redis_client.delete(registry_key)
        logger.info("[SessionRegistry] Registry cleared worker_type=%s", worker_type)
        return True
    except Exception as exc:
        logger.warning("[SessionRegistry] Clear failed worker_type=%s error=%s", worker_type, exc)
        return False


def get_all_registries() -> dict[str, int]:
    """Get count of sessions in each registry across all worker types."""
    try:
        redis_client = _get_redis_client()
        if redis_client is None:
            return {}
        
        # Scan for all keys matching the pattern
        results = {}
        pattern = "session_lru_registry:*"
        for key in redis_client.scan_iter(pattern):
            count = redis_client.zcard(key)
            worker_type = key.replace("session_lru_registry:", "")
            results[worker_type] = count or 0
        return results
    except Exception as exc:
        logger.warning("[SessionRegistry] Get all registries failed: %s", exc)
        return {}
