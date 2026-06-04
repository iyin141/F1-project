"""Compatibility wrapper around the canonical cache service.

This module preserves the historical public API expected by callers
(`build_cache_key(year, round, session, data_type)`, `get_from_cache(key)`)
while delegating newer, canonical operations to
`api.services.cache_service`.

The repository currently mixes two cache helper implementations; this
wrapper smooths over differences during migration.
"""

from __future__ import annotations

from typing import Any, Optional

from django.core.cache import caches

from api.services import cache_service as cs


def build_cache_key(year: int, round_number: int, session: str, data_type: str) -> str:
    """Compatibility shim matching historical signature.

    Delegates to `cache_service.build_cache_key(data_type, year, round, session)`.
    """
    return cs.build_cache_key(data_type, year, round_number, session)


def ttl_for(data_type: str, year: int) -> int:
    """Delegate to canonical TTL function."""
    return cs.ttl_for(data_type, year)


def get_from_cache(*args, **kwargs) -> Optional[Any]:
    """Flexible getter:

    - `get_from_cache(key: str)` -> returns cached value (legacy callers)
    - `get_from_cache(data_type, year, round_number, session, model_queryset=None)` ->
       delegates to `cache_service.get_from_cache` and returns only the data part
       (keeps backward-compatible return shape).
    """
    # Legacy single-key usage
    if len(args) == 1 and isinstance(args[0], str):
        key = args[0]
        cache = caches["default"]
        return cache.get(key)

    # New canonical signature: delegate and return only the data portion
    try:
        data, _source = cs.get_from_cache(*args, **kwargs)
        return data
    except TypeError:
        # Fall back to legacy behavior if signature doesn't match
        return None


def set_in_cache(key: str, data: Any, ttl: int = 300) -> None:
    """Set a cache value by explicit key (delegates to canonical implementation)."""
    return cs.set_in_cache(key, data, timeout=ttl)


def cache_clear_pattern(pattern: str) -> None:
    """Clear cache entries matching pattern (best-effort).

    Delegates to simple cache operations; may be inefficient on some backends.
    """
    cache = caches["default"]
    if hasattr(cache, "delete_many"):
        try:
            # Redis-backed cache: use scan via raw client if available
            cache.delete_many([k for k in getattr(cache, "_cache", {}).keys() if k.startswith(pattern)])
        except Exception:
            pass
    elif hasattr(cache, "_cache"):
        keys_to_delete = [k for k in cache._cache.keys() if k.startswith(pattern)]
        for k in keys_to_delete:
            cache.delete(k)

