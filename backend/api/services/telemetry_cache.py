"""
Telemetry cache service — Phase 3, Problem #19: Dedicated telemetry subsystem.

Handles read/write of telemetry data to a dedicated Redis 2 instance (CACHES["telemetry_cache"])
with appropriate TTLs and capacity management for tier4 workers.

Telemetry cache key format:
  - Single trace: telemetry:trace:{year}:{round}:{session}:{driver}:{lap}:{stride}:{limit_points}
  - Overlay: telemetry:overlay:{year}:{round}:{session}:{lap}
  - Summary: telemetry:summary:{year}:{round}:{session}:{driver}
  - Grid summary: telemetry:grid:{year}:{round}:{session}

TTLs:
  - Single trace: 30 min (1800s)
  - Overlay: 30 min (1800s)
  - Compare: 1h (3600s)
  - Grid summary: 2h (7200s)
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Any

from django.core.cache import caches

logger = logging.getLogger(__name__)

# Cache alias for telemetry (Phase 4 adds this to settings)
TELEMETRY_CACHE_ALIAS = "telemetry_cache"

# TTL ladder for telemetry data (seconds)
TTL_SINGLE_TRACE = 1800  # 30 min
TTL_OVERLAY = 1800  # 30 min
TTL_COMPARE = 3600  # 1h
TTL_GRID_SUMMARY = 7200  # 2h


def _get_telemetry_cache():
    """Get the telemetry cache backend; fallback to default if not configured."""
    try:
        return caches[TELEMETRY_CACHE_ALIAS]
    except KeyError:
        logger.warning(
            "[TelemetryCache] %s not configured; falling back to default cache",
            TELEMETRY_CACHE_ALIAS,
        )
        return caches["default"]


def build_trace_key(year: int, round_number: int, session: str, driver: str, lap: int, stride: int, limit_points: int) -> str:
    """Build cache key for a single telemetry trace."""
    return f"telemetry:trace:{year}:{round_number}:{session}:{driver}:{lap}:{stride}:{limit_points}"


def build_overlay_key(year: int, round_number: int, session: str, lap: int) -> str:
    """Build cache key for telemetry overlay."""
    return f"telemetry:overlay:{year}:{round_number}:{session}:{lap}"


def build_summary_key(year: int, round_number: int, session: str, driver: str) -> str:
    """Build cache key for telemetry summary."""
    return f"telemetry:summary:{year}:{round_number}:{session}:{driver}"


def build_grid_key(year: int, round_number: int, session: str) -> str:
    """Build cache key for grid summary."""
    return f"telemetry:grid:{year}:{round_number}:{session}"


def get_trace(year: int, round_number: int, session: str, driver: str, lap: int, stride: int, limit_points: int) -> Optional[list]:
    """
    Retrieve cached telemetry trace.
    
    Returns list of telemetry points or None if not cached.
    """
    key = build_trace_key(year, round_number, session, driver, lap, stride, limit_points)
    try:
        cache = _get_telemetry_cache()
        data = cache.get(key)
        if data is not None:
            logger.debug("[TelemetryCache] trace hit key=%s", key)
            return json.loads(data) if isinstance(data, str) else data
        logger.debug("[TelemetryCache] trace miss key=%s", key)
        return None
    except Exception as exc:
        logger.warning("[TelemetryCache] get_trace failed key=%s error=%s", key, exc)
        return None


def set_trace(year: int, round_number: int, session: str, driver: str, lap: int, stride: int, limit_points: int, data: list) -> bool:
    """
    Cache a telemetry trace with TTL_SINGLE_TRACE (30 min).
    
    Returns True if set, False on error.
    """
    key = build_trace_key(year, round_number, session, driver, lap, stride, limit_points)
    try:
        cache = _get_telemetry_cache()
        # Store as JSON string to handle serialization across cache backends
        cache.set(key, json.dumps(data), timeout=TTL_SINGLE_TRACE)
        logger.debug("[TelemetryCache] trace set key=%s ttl=%ds points=%d", key, TTL_SINGLE_TRACE, len(data))
        return True
    except Exception as exc:
        logger.warning("[TelemetryCache] set_trace failed key=%s error=%s", key, exc)
        return False


def get_overlay(year: int, round_number: int, session: str, lap: int) -> Optional[dict]:
    """
    Retrieve cached telemetry overlay.
    
    Returns dict of overlay data or None if not cached.
    """
    key = build_overlay_key(year, round_number, session, lap)
    try:
        cache = _get_telemetry_cache()
        data = cache.get(key)
        if data is not None:
            logger.debug("[TelemetryCache] overlay hit key=%s", key)
            return json.loads(data) if isinstance(data, str) else data
        logger.debug("[TelemetryCache] overlay miss key=%s", key)
        return None
    except Exception as exc:
        logger.warning("[TelemetryCache] get_overlay failed key=%s error=%s", key, exc)
        return None


def set_overlay(year: int, round_number: int, session: str, lap: int, data: dict) -> bool:
    """
    Cache telemetry overlay with TTL_OVERLAY (30 min).
    
    Returns True if set, False on error.
    """
    key = build_overlay_key(year, round_number, session, lap)
    try:
        cache = _get_telemetry_cache()
        cache.set(key, json.dumps(data), timeout=TTL_OVERLAY)
        logger.debug("[TelemetryCache] overlay set key=%s ttl=%ds", key, TTL_OVERLAY)
        return True
    except Exception as exc:
        logger.warning("[TelemetryCache] set_overlay failed key=%s error=%s", key, exc)
        return False


def get_summary(year: int, round_number: int, session: str, driver: str) -> Optional[dict]:
    """
    Retrieve cached telemetry summary.
    
    Returns dict of summary data or None if not cached.
    """
    key = build_summary_key(year, round_number, session, driver)
    try:
        cache = _get_telemetry_cache()
        data = cache.get(key)
        if data is not None:
            logger.debug("[TelemetryCache] summary hit key=%s", key)
            return json.loads(data) if isinstance(data, str) else data
        logger.debug("[TelemetryCache] summary miss key=%s", key)
        return None
    except Exception as exc:
        logger.warning("[TelemetryCache] get_summary failed key=%s error=%s", key, exc)
        return None


def set_summary(year: int, round_number: int, session: str, driver: str, data: dict) -> bool:
    """
    Cache telemetry summary with TTL_SINGLE_TRACE (30 min).
    
    Returns True if set, False on error.
    """
    key = build_summary_key(year, round_number, session, driver)
    try:
        cache = _get_telemetry_cache()
        cache.set(key, json.dumps(data), timeout=TTL_SINGLE_TRACE)
        logger.debug("[TelemetryCache] summary set key=%s ttl=%ds", key, TTL_SINGLE_TRACE)
        return True
    except Exception as exc:
        logger.warning("[TelemetryCache] set_summary failed key=%s error=%s", key, exc)
        return False


def get_grid_summary(year: int, round_number: int, session: str) -> Optional[dict]:
    """
    Retrieve cached grid summary (all drivers fastest-lap traces for a session).
    
    Returns dict or None if not cached.
    """
    key = build_grid_key(year, round_number, session)
    try:
        cache = _get_telemetry_cache()
        data = cache.get(key)
        if data is not None:
            logger.debug("[TelemetryCache] grid hit key=%s", key)
            return json.loads(data) if isinstance(data, str) else data
        logger.debug("[TelemetryCache] grid miss key=%s", key)
        return None
    except Exception as exc:
        logger.warning("[TelemetryCache] get_grid_summary failed key=%s error=%s", key, exc)
        return None


def set_grid_summary(year: int, round_number: int, session: str, data: dict) -> bool:
    """
    Cache grid summary with TTL_GRID_SUMMARY (2h).
    
    Returns True if set, False on error.
    """
    key = build_grid_key(year, round_number, session)
    try:
        cache = _get_telemetry_cache()
        cache.set(key, json.dumps(data), timeout=TTL_GRID_SUMMARY)
        logger.debug("[TelemetryCache] grid set key=%s ttl=%ds", key, TTL_GRID_SUMMARY)
        return True
    except Exception as exc:
        logger.warning("[TelemetryCache] set_grid_summary failed key=%s error=%s", key, exc)
        return False


def invalidate_session(year: int, round_number: int, session: str) -> int:
    """
    Invalidate all telemetry cache entries for a session.
    
    Returns count of keys deleted.
    """
    # Note: This is a best-effort invalidation. Redis doesn't support pattern deletion
    # without scanning all keys. For production, use Redis SCAN or maintain a set of keys.
    # For now, we just log that this would need custom implementation.
    logger.info("[TelemetryCache] invalidate_session called year=%s round=%s session=%s", year, round_number, session)
    return 0
