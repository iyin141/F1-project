"""Response cache for chaos endpoints on the `default` alias (Redis 1, the app cache; telemetry_cache is for telemetry).
Keys carry a version number that is bumped whenever a ModelRun is saved, which invalidates every cached response at once."""
import logging
import time

from django.core.cache import caches

logger = logging.getLogger(__name__)
ALIAS = "default"
VERSION_KEY = "chaos:version"
TTL_PREDICTIONS = 6 * 3600  # race / drivers / laps: only change with a new ModelRun (version bump)
TTL_HISTORY = 3600          # circuit history, driver profile: change when labels change
TTL_MODEL = 600             # model page


def _cache():
    return caches[ALIAS]


def version() -> str:
    try:
        v = _cache().get(VERSION_KEY)
        if v is None:
            v = time.time_ns()
            _cache().set(VERSION_KEY, v, timeout=None)
        return str(v)
    except Exception:  # noqa: BLE001  cache down: no caching, never an error
        return "0"


def bump_version():
    try:
        _cache().set(VERSION_KEY, time.time_ns(), timeout=None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[chaos] cache version bump failed: %s", exc)


def cached(key: str, ttl: int, build):
    """Return build() cached under key+version. A cache outage falls back to building every time."""
    full = f"chaos:{version()}:{key}"
    try:
        hit = _cache().get(full)
        if hit is not None:
            return hit
    except Exception:  # noqa: BLE001
        return build()
    value = build()
    if value is not None:
        try:
            _cache().set(full, value, timeout=ttl)
        except Exception:  # noqa: BLE001
            pass
    return value
