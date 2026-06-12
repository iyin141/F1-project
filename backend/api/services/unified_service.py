"""Unified FastF1 data extraction service with intelligent caching and normalization."""
from __future__ import annotations

import logging
import math
import os
import time
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from .fastf1_runtime import fastf1
from .readiness import is_data_unavailable_error
from api.common.request_id import get_request_id

logger = logging.getLogger(__name__)

# Constants
_ALLOWED_SESSIONS = {"R", "Q", "S", "SQ", "FP1", "FP2", "FP3"}
_MAX_LIMIT = 2000
_MAX_TELEMETRY_POINTS = 3000
_DEFAULT_TELEMETRY_POINTS = 800

# Minimal FastF1 load requirements per data type.
# Authoritative single source of truth for all session.load() requirements.
# Used by SessionManager, populate_session, management commands, and analysis workers.
#
# All entries map to the 4 core FastF1 session.load() flags:
#   - telemetry: Load high-frequency telemetry data
#   - weather: Load weather condition snapshots
#   - messages: Load incident/safety car messages
#   - laps: Load lap timing and metadata
#
# Unknown types safely fall back to _FULL_LOAD.
_LOAD_REQUIREMENTS: dict[str, dict[str, bool]] = {
    # Session Data Types (unified 6-model architecture)
    "weather":           {"telemetry": False, "weather": True,  "messages": False, "laps": False},
    "pit_stops":         {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "incidents":         {"telemetry": False, "weather": False, "messages": True,  "laps": False},
    "positions":         {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "drs":               {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "track_status":      {"telemetry": False, "weather": False, "messages": False, "laps": True},

    # Legacy/Variant Names (for backward compatibility)
    "results":           {"telemetry": False, "weather": False, "messages": False, "laps": False},
    "telemetry":         {"telemetry": True,  "weather": False, "messages": False, "laps": True},
    "laps":              {"telemetry": False, "weather": False, "messages": False, "laps": True},

    # Race Result Types
    "race_results":      {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "qualifying_results":{"telemetry": False, "weather": False, "messages": False, "laps": True},
    "practice_results":  {"telemetry": False, "weather": False, "messages": False, "laps": True},

    # Lap & Position Types
    "paginate_laps":     {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "paginate_positions":{"telemetry": False, "weather": False, "messages": False, "laps": True},
    "paginate_telemetry":{"telemetry": True,  "weather": False, "messages": False, "laps": True},

    # Analysis & Derived Types (require lap data, no additional FastF1 load)
    "stint_analysis":    {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "pace_analysis":     {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "sector_analysis":   {"telemetry": False, "weather": False, "messages": False, "laps": True},
    "tyre_strategy":     {"telemetry": False, "weather": False, "messages": False, "laps": True},
}

# Full load — used when required_types is None (backward-compatible default).
_FULL_LOAD: dict[str, bool] = {"telemetry": True, "weather": True, "messages": True, "laps": True}


def resolve_load_params(required_types: list[str]) -> dict[str, bool]:
    """
    Compute the minimal session.load() kwargs for the given data type list.

    ORs requirements across all requested types so a single session.load()
    satisfies every extractor.  Unknown types fall back to _FULL_LOAD to
    guarantee correctness.
    
    Uses _LOAD_REQUIREMENTS for all data type mappings (unified single source of truth).
    Supported types include session data (weather, pit_stops, incidents, positions, drs, track_status),
    result types (race_results, qualifying_results), and analysis types (stint_analysis, pace_analysis, etc.).
    """
    params: dict[str, bool] = {"telemetry": False, "weather": False, "messages": False, "laps": False}
    for dtype in required_types:
        reqs = _LOAD_REQUIREMENTS.get(dtype)
        if reqs is None:
            return _FULL_LOAD.copy()  # Unknown type — safe fallback
        for key, needed in reqs.items():
            if needed:
                params[key] = True
    return params


def _is_unsupported_session_error(exc: Exception) -> bool:
    return is_data_unavailable_error(exc)


class SessionManager:
    """
    Intelligent FastF1 session loader with bounded LRU caching and request coalescing.
    
    Per-worker caps (Phase 4 Problem #5):
    - Gunicorn workers: 5–7 sessions (non-telemetry profiles, ~5–20MB each)
    - Tier3 medium workers: 4 sessions (laps profile, ~20MB each)
    - Tier4 telemetry workers: 3 sessions (full profile, ~80–100MB each)
    
    Request coalescing: When multiple requests arrive for the same session while one
    is loading, they wait for the first load to complete and reuse the result.
    """

    _cache: dict[str, Any] = {}
    _cache_timestamps: dict[str, float] = {}  # Track access time for LRU eviction
    _loading_events: dict[str, threading.Event] = {}  # Track in-flight loads for coalescing
    _cache_info = {"hits": 0, "misses": 0, "evictions": 0, "coalesced": 0}

    @staticmethod
    def _get_worker_type_and_cap() -> tuple[str, int]:
        """
        Determine worker type and session cache cap based on process context.
        
        Returns: (worker_type, cap)
        """
        # Check if running in Celery worker
        worker_name = os.getenv("CELERY_WORKER_NAME", "")
        if "tier4_telemetry" in worker_name:
            return "tier4_telemetry", 3
        elif "tier3_medium" in worker_name:
            return "tier3_medium", 4
        elif "tier2_fast" in worker_name:
            return "tier2_fast", 5
        elif "tier1_instant" in worker_name:
            return "tier1_instant", 5
        elif worker_name.startswith("celery"):
            return "celery_generic", 5
        
        # Default: Gunicorn/Django worker
        return "gunicorn", 6

    @classmethod
    def get_session(
        cls,
        year: int,
        round_number: int,
        session_type: str,
        required_types: list[str] | None = None,
    ):
        """
        Load or retrieve cached FastF1 session with bounded LRU eviction and request coalescing.
        
        Request coalescing: If another request is already loading this session, wait for it
        to complete instead of triggering a duplicate load.

        Args:
            year: Season year.
            round_number: Round number within the season.
            session_type: Session type string (R, Q, FP1, ...).
            required_types: List of data-type keys (e.g. ['weather', 'pit_stops']).
                Determines the minimal session.load() flags needed.
        """
        session_type = str(session_type).upper()
        if session_type not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")

        # Resolve the minimal set of load flags for this request.
        load_params = resolve_load_params(required_types) if required_types is not None else _FULL_LOAD.copy()

        # Cache key is session-scoped only; upgrade logic handles mismatched load flags.
        cache_key = f"{year}:{round_number}:{session_type}"

        # Cache hit — check if cached session satisfies this request's load requirements
        if cache_key in cls._cache:
            cached_session = cls._cache[cache_key]
            # If a previous load recorded that this session is unsupported
            # (e.g. partial load with a _load_error), prefer returning the
            # cached partial session only when it already contains the data
            # being requested. Otherwise attempt to reload so callers that
            # patch FastF1 get_session (tests) are honored.
            if getattr(cached_session, "_load_error", None) is not None:
                def _has_dataset(sess, attr_name: str) -> bool:
                    try:
                        ds = getattr(sess, attr_name, None)
                    except Exception:
                        return False
                    if ds is None:
                        return False
                    if hasattr(ds, "empty"):
                        try:
                            return not bool(ds.empty)
                        except Exception:
                            return False
                    return True

                # If no specific required_types were requested, the cached
                # partial session is the safest thing to return.
                if not required_types:
                    cls._cache_timestamps[cache_key] = time.time()
                    cls._cache_info["hits"] += 1
                    logger.info(
                        "event=session_cache_hit_partial",
                        extra={
                            "request_id": get_request_id(),
                            "year": year,
                            "round": round_number,
                            "session_type": session_type,
                        },
                    )
                    return cached_session

                # Map requested type names to session attribute names
                _type_to_attr = {
                    "laps": "laps",
                    "results": "results",
                    "weather": "weather",
                    "incidents": "messages",
                    "telemetry": "telemetry",
                }

                # If the cached session already satisfies all requested
                # types, return it; otherwise fall through and attempt a
                # fresh load so tests that patch get_session are executed.
                missing = []
                for t in required_types or []:
                    attr = _type_to_attr.get(t, t)
                    if not _has_dataset(cached_session, attr):
                        missing.append(t)

                if not missing:
                    cls._cache_timestamps[cache_key] = time.time()
                    cls._cache_info["hits"] += 1
                    logger.info(
                        "event=session_cache_hit_partial",
                        extra={
                            "request_id": get_request_id(),
                            "year": year,
                            "round": round_number,
                            "session_type": session_type,
                        },
                    )
                    return cached_session
            cached_flags = getattr(cached_session, "_loaded_flags", {})
            needs_upgrade = any(
                load_params.get(flag) and not cached_flags.get(flag)
                for flag in ["telemetry", "weather", "messages", "laps"]
            )
            if not needs_upgrade:
                cls._cache_timestamps[cache_key] = time.time()
                cls._cache_info["hits"] += 1
                logger.info(
                    "event=session_cache_hit",
                    extra={
                        "request_id": get_request_id(),
                        "year": year,
                        "round": round_number,
                        "session_type": session_type,
                    },
                )
                return cached_session
            # Cached session exists but lacks required data — fall through to reload
            logger.info(
                "event=session_cache_upgrade year=%s round=%s session_type=%s",
                year, round_number, session_type,
            )

        # Request coalescing: Check if another request is already loading this session
        loading_event = cls._loading_events.get(cache_key)
        if loading_event is not None:
            logger.info(
                "event=session_coalesce_wait",
                extra={
                    "request_id": get_request_id(),
                    "year": year,
                    "round": round_number,
                    "session_type": session_type,
                },
            )
            # Wait for the in-flight load to complete
            coalesce_start = time.time()
            loading_event.wait(timeout=300)  # Max 5 min wait
            coalesce_ms = (time.time() - coalesce_start) * 1000
            cls._cache_info["coalesced"] += 1
            
            logger.info(
                "event=session_coalesce_complete",
                extra={
                    "request_id": get_request_id(),
                    "year": year,
                    "round": round_number,
                    "session_type": session_type,
                    "coalesce_ms": f"{coalesce_ms:.1f}",
                },
            )
            
            # After waiting, check cache again
            if cache_key in cls._cache:
                cached_session = cls._cache[cache_key]
                cached_flags = getattr(cached_session, "_loaded_flags", {})
                needs_upgrade_after_wait = any(
                    load_params.get(flag) and not cached_flags.get(flag)
                    for flag in ["telemetry", "weather", "messages", "laps"]
                )
                if not needs_upgrade_after_wait:
                    cls._cache_timestamps[cache_key] = time.time()
                    cls._cache_info["hits"] += 1
                    return cached_session
            # If loading_event was removed or load failed, fall through to load
        
        # Cache miss — load from FastF1
        cls._cache_info["misses"] += 1
        
        logger.info(
            "event=session_load_start",
            extra={
                "request_id": get_request_id(),
                "year": year,
                "round": round_number,
                "session_type": session_type,
                "load_params": str(load_params),
            },
        )
        
        # Create loading event for request coalescing
        loading_event = threading.Event()
        cls._loading_events[cache_key] = loading_event
        
        primary_error = None
        fallback_error = None
        load_start_time = time.time()

        try:
            # Primary strategy: load by round number
            try:
                try:
                    session = fastf1.get_session(year, round_number, session_type)
                except ValueError as ve:
                    if session_type == "SQ" and "does not exist" in str(ve):
                        logger.info("event=session_load_sq_fallback year=%s round=%s", year, round_number)
                        session = fastf1.get_session(year, round_number, "Sprint Shootout")
                    else:
                        raise
                # Retry loop for session.load() to handle bad proxy IPs
                max_retries = 5
                for attempt in range(max_retries):
                    download_start = time.time()
                    try:
                        try:
                            session.load(**load_params)
                        except TypeError as te:
                            # Some test fakes or legacy session implementations don't accept
                            # keyword args; fall back to calling load() without kwargs.
                            logger.info("event=session_load_kwarg_retry", extra={"error": str(te)})
                            session.load()
                            
                        # VERIFY the data actually loaded. FastF1 sometimes swallows proxy errors 
                        # and emits warnings instead of exceptions (e.g. Ergast failures).
                        if load_params.get("laps"):
                            # This will throw an exception if laps failed to initialize properly
                            _ = session.laps
                            
                        # If we get here, load was fully successful
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"event=session_load_retry attempt={attempt+1} error={str(e)}")
                            import time as time_lib
                            time_lib.sleep(2)  # Wait for rotating proxy to cycle IP
                        else:
                            raise e

                session._loaded_flags = load_params.copy()
                download_ms = (time.time() - download_start) * 1000
                
                # Phase 4: Check LRU cap before caching
                cls._maybe_evict_lru()
                
                cls._cache[cache_key] = session
                cls._cache_timestamps[cache_key] = time.time()
                loading_event.set()  # Signal that load is complete
                return session
            except Exception as exc:
                primary_error = exc
                if "session" in locals() and _is_unsupported_session_error(exc):
                    # Preserve the load exception on the session so callers
                    # (helpers/services) can classify it and return the
                    # appropriate readiness messages.
                    try:
                        setattr(session, "_load_error", exc)
                    except Exception:
                        logger.warning("Failed to attach load error to session object")
                    cls._maybe_evict_lru()
                    cls._cache[cache_key] = session
                    cls._cache_timestamps[cache_key] = time.time()
                    loading_event.set()  # Signal that load is complete (partially)
                    return session

            # Fallback strategy: map round to event name, then load by event name
            schedule = fastf1.get_event_schedule(year)
            event_rows = schedule[schedule["RoundNumber"] == round_number]
            if event_rows.empty:
                raise ValueError(f"No event found for year={year}, round={round_number}")

            event_name = str(event_rows.iloc[0]["EventName"])
            try:
                session = fastf1.get_session(year, event_name, session_type)
            except ValueError as ve:
                if session_type == "SQ" and "does not exist" in str(ve):
                    logger.info("event=session_load_sq_fallback_event year=%s round=%s", year, round_number)
                    session = fastf1.get_session(year, event_name, "Sprint Shootout")
                else:
                    raise
            download_start = time.time()
            try:
                session.load(**load_params)
            except TypeError as te:
                logger.info("event=session_load_kwarg_retry", extra={"error": str(te)})
                session.load()
            session._loaded_flags = load_params.copy()
            download_ms = (time.time() - download_start) * 1000
            
            total_ms = (time.time() - load_start_time) * 1000
            
            logger.info(
                "event=session_load_complete",
                extra={
                    "request_id": get_request_id(),
                    "year": year,
                    "round": round_number,
                    "session_type": session_type,
                    "total_ms": f"{total_ms:.1f}",
                    "download_ms": f"{download_ms:.1f}",
                    "source": "event_name_fallback",
                },
            )
            
            # Phase 4: Check LRU cap before caching
            cls._maybe_evict_lru()
            
            cls._cache[cache_key] = session
            cls._cache_timestamps[cache_key] = time.time()
            loading_event.set()  # Signal that load is complete
            return session
        except Exception as exc:
            fallback_error = exc
            if "session" in locals() and _is_unsupported_session_error(exc):
                try:
                    setattr(session, "_load_error", exc)
                except Exception:
                    logger.warning("Failed to attach load error to session object")
                cls._maybe_evict_lru()
                cls._cache[cache_key] = session
                cls._cache_timestamps[cache_key] = time.time()
                loading_event.set()  # Signal that load is complete (partially)
                return session
            
            # Both strategies failed
            loading_event.set()  # Signal that load failed
            raise Exception(
                f"Failed to load session {year} R{round_number} {session_type}. "
                f"Primary error: {str(primary_error)}. "
                f"Fallback error: {str(fallback_error)}"
            )
        finally:
            # Clean up loading event after a delay (other requests may still be waiting)
            import atexit
            def cleanup():
                cls._loading_events.pop(cache_key, None)
            # Use a timer to delay cleanup (give waiting requests time to check cache)
            timer = threading.Timer(0.1, cleanup)
            timer.daemon = True
            timer.start()

    @classmethod
    def _maybe_evict_lru(cls) -> None:
        """
        Evict least recently used session if cache exceeds per-worker cap.
        """
        _, cap = cls._get_worker_type_and_cap()
        
        # Check if we've exceeded the cap
        if len(cls._cache) < cap:
            return
        
        # Find the least recently used key (oldest timestamp)
        if not cls._cache_timestamps:
            return
        
        lru_key = min(cls._cache_timestamps, key=cls._cache_timestamps.get)
        
        # Evict
        if lru_key in cls._cache:
            del cls._cache[lru_key]
        if lru_key in cls._cache_timestamps:
            del cls._cache_timestamps[lru_key]
        
        cls._cache_info["evictions"] += 1
        worker_type, _ = cls._get_worker_type_and_cap()
        print(f"[SessionManager] LRU eviction worker_type={worker_type} evicted_key={lru_key} cache_size={len(cls._cache)}")
    @classmethod
    def clear_cache(cls):
        """Clear all cached sessions."""
        cls._cache.clear()
        cls._cache_info = {"hits": 0, "misses": 0, "evictions": 0, "coalesced": 0}

    @classmethod
    def get_cache_stats(cls) -> dict:
        """Return cache hit/miss statistics."""
        total = cls._cache_info["hits"] + cls._cache_info["misses"]
        hit_rate = (cls._cache_info["hits"] / total * 100) if total > 0 else 0.0
        return {
            "cached_sessions": len(cls._cache),
            "hits": cls._cache_info["hits"],
            "misses": cls._cache_info["misses"],
            "hit_rate_percent": round(hit_rate, 2),
        }


class DataNormalizer:
    """Centralized data normalization to handle type conversions, NaN/None consistently."""

    @staticmethod
    def to_int(value: Any) -> Optional[int]:
        """Convert value to integer, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_float(value: Any, precision: int = 3) -> Optional[float]:
        """Convert value to float with precision, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        try:
            return round(float(value), precision)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_str(value: Any) -> Optional[str]:
        """Convert value to string, return None if invalid/NaN."""
        if value is None or pd.isna(value):
            return None
        return str(value)

    @staticmethod
    def to_bool(value: Any) -> bool:
        """Convert value to boolean, treat NaN/None as False."""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False
        return bool(value)

    @staticmethod
    def to_time_seconds(value: Any, precision: int = 4) -> Optional[float]:
        """Convert timedelta or time string to seconds."""
        if value is None or pd.isna(value):
            return None

        # Already a timedelta
        if hasattr(value, "total_seconds"):
            return DataNormalizer.to_float(value.total_seconds(), precision)

        # Try to convert to timedelta
        try:
            td = pd.to_timedelta(value)
            return DataNormalizer.to_float(td.total_seconds(), precision)
        except Exception:
            return None

    @staticmethod
    def to_timedelta_str(value: Any) -> Optional[str]:
        """Convert time value to HH:MM:SS.mmm string format."""
        if value is None or pd.isna(value):
            return None
        return str(value)

    @staticmethod
    def safe_get(df: Optional[pd.DataFrame], col: str, default: Any = None) -> Any:
        """Safely get column from dataframe, return default if not exists."""
        if df is None or col not in df.columns:
            return default
        return df[col]

    @staticmethod
    def fill_na(series: pd.Series, fill_value: Any = 0) -> pd.Series:
        """Fill NA values in series."""
        if series is None or series.empty:
            return series
        return series.fillna(fill_value)

    @staticmethod
    def normalize_session_type(session_type: str) -> str:
        """Normalize session type string to uppercase, validate."""
        normalized = str(session_type).upper()
        if normalized not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")
        return normalized

    @staticmethod
    def normalize_driver_code(driver_code: Optional[str]) -> Optional[str]:
        """Normalize driver code to uppercase."""
        if driver_code is None:
            return None
        return str(driver_code).upper()


class DataValidator:
    """Validation utility for FastF1 data constraints and field requirements."""

    @staticmethod
    def validate_year(year: int):
        """Validate year is reasonable (1950+)."""
        if not isinstance(year, int):
            raise ValueError("year must be an integer")
        if year < 1950 or year > 2100:
            raise ValueError(f"year {year} is out of valid F1 range (1950-2100)")

    @staticmethod
    def validate_round(round_number: int):
        """Validate round is in valid range."""
        if not isinstance(round_number, int):
            raise ValueError("round_number must be an integer")
        if round_number < 1 or round_number > 24:
            raise ValueError(f"round_number {round_number} must be between 1 and 24")

    @staticmethod
    def validate_session_type(session_type: str):
        """Validate session type."""
        normalized = str(session_type).upper()
        if normalized not in _ALLOWED_SESSIONS:
            raise ValueError(f"session_type must be one of {_ALLOWED_SESSIONS}")
        return normalized

    @staticmethod
    def validate_lap_number(lap_number: int, max_laps: int):
        """Validate lap number within session."""
        if not isinstance(lap_number, int):
            raise ValueError("lap_number must be an integer")
        if lap_number < 1 or lap_number > max_laps:
            raise ValueError(f"lap_number {lap_number} must be between 1 and {max_laps}")

    @staticmethod
    def validate_sector_window(sector_start: Optional[int], sector_end: Optional[int]):
        """Validate sector start/end parameters."""
        if sector_start is None and sector_end is None:
            return

        if sector_start is None or sector_end is None:
            raise ValueError("sector_start and sector_end must be provided together")

        if not isinstance(sector_start, int) or not isinstance(sector_end, int):
            raise ValueError("sector_start and sector_end must be integers")

        if sector_start < 1 or sector_start > 3 or sector_end < 1 or sector_end > 3:
            raise ValueError("sector_start and sector_end must be between 1 and 3")

        if sector_start > sector_end:
            raise ValueError("sector_start must be less than or equal to sector_end")

    @staticmethod
    def validate_stride(stride: int):
        """Validate telemetry stride parameter."""
        if not isinstance(stride, int):
            raise ValueError("stride must be an integer")
        if stride < 1:
            raise ValueError("stride must be positive")

    @staticmethod
    def validate_limit(limit: Optional[int]):
        """Validate limit parameter."""
        if limit is None:
            return
        if not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be a positive integer")

    @staticmethod
    def validate_non_empty(data: Any, field_name: str = "data"):
        """Validate data is not empty."""
        if data is None or (hasattr(data, "__len__") and len(data) == 0):
            raise ValueError(f"{field_name} cannot be empty")

    @staticmethod
    def validate_dataframe(df: pd.DataFrame, min_rows: int = 1) -> bool:
        """Validate dataframe has minimum rows and is not all NaN."""
        if df is None or df.empty:
            return False
        if len(df) < min_rows:
            return False
        return True


class BaseDataExtractor(ABC):
    """Abstract base class for all FastF1 data extractors."""

    def __init__(
        self,
        session: Any,
        year: int,
        round_number: int,
        session_type: str,
        driver: Optional[str] = None,
        limit: Optional[int] = None,
    ):
        """
        Initialize extractor.

        Args:
            session: FastF1 session object (from SessionManager)
            year: Race year
            round_number: Round number
            session_type: Session type (R, Q, FP1, FP2, FP3)
            driver: Optional driver code filter
            limit: Optional row limit
        """
        self.session = session
        self.year = year
        self.round_number = round_number
        self.session_type = DataNormalizer.normalize_session_type(session_type)
        self.driver = DataNormalizer.normalize_driver_code(driver)
        self.limit = self._validate_limit(limit)

    @staticmethod
    def _validate_limit(limit: Optional[int]) -> Optional[int]:
        """Validate limit parameter."""
        if limit is None:
            return None
        if limit < 1:
            raise ValueError("limit must be a positive integer")
        return min(limit, _MAX_LIMIT)

    @abstractmethod
    def extract(self, **kwargs) -> dict:
        """
        Extract and return normalized data.
        Must return dict with structure:
        {
            "meta": {...},
            "filters_applied": {...},
            "data": [...]
        }
        """
        pass

    def _build_response(
        self,
        data_rows: list[dict],
        additional_meta: Optional[dict] = None,
        additional_filters: Optional[dict] = None,
    ) -> dict:
        """
        Build standard response object.

        Args:
            data_rows: List of normalized data rows
            additional_meta: Optional extra metadata fields
            additional_filters: Optional extra filter fields
        """
        meta = {
            "year": self.year,
            "round": self.round_number,
            "session": self.session_type,
            "row_count": len(data_rows),
            "extracted_at": datetime.now().isoformat(),
            "limit_max": _MAX_LIMIT,
        }
        if additional_meta:
            meta.update(additional_meta)

        filters = {
            "driver": self.driver,
            "limit": self.limit,
        }
        if additional_filters:
            filters.update(additional_filters)

        return {
            "meta": meta,
            "filters_applied": filters,
            "data": data_rows,
        }

    def _pick_drivers(self, drivers_list: list[str]) -> list[str]:
        """Filter drivers list by self.driver if set."""
        if not self.driver:
            return drivers_list
        return [d for d in drivers_list if str(d).upper() == self.driver]


# ============================================================================
# Concrete Extractors - implement specific data extraction workflows
# ============================================================================


class TelemetryExtractor(BaseDataExtractor):
    """Extract and aggregate telemetry data for drivers and laps."""

    def extract(
        self,
        driver: Optional[str] = None,
        lap: Optional[int] = None,
        limit_points: int = _DEFAULT_TELEMETRY_POINTS,
        stride: int = 1,
        sector_start: Optional[int] = None,
        sector_end: Optional[int] = None,
    ) -> dict:
        """
        Extract telemetry for specified driver/lap or all drivers' best laps.

        Args:
            driver: Optional driver code override
            lap: Optional specific lap number
            limit_points: Maximum telemetry points to return (default 800)
            stride: Sampling stride (every nth point)
            sector_start: Optional sector window start (1-3)
            sector_end: Optional sector window end (1-3)
        """
        # Use provided driver or instance driver
        target_driver = str(driver or self.driver)
        if not target_driver:
            raise ValueError("driver parameter is required")

        # Validate parameters
        DataValidator.validate_stride(stride)
        if limit_points < 1 or limit_points > _MAX_TELEMETRY_POINTS:
            raise ValueError(f"limit_points must be between 1 and {_MAX_TELEMETRY_POINTS}")
        DataValidator.validate_sector_window(sector_start, sector_end)

        try:
            if getattr(self.session, "_load_error", None) is not None:
                raise Exception("Session data could not be fully loaded due to FastF1 errors.")
            try:
                laps = self.session.laps.pick_drivers([target_driver])
            except Exception:
                return self._build_response([], additional_filters={"driver": target_driver})
            
            if laps.empty:
                raise ValueError(f"No laps found for driver {target_driver}")

            # Determine which lap to extract
            selected_lap_number = lap
            if selected_lap_number is None:
                valid_laps = laps[laps["LapTime"].notna()]
                if valid_laps.empty:
                    raise ValueError(f"No valid lap times for driver {target_driver}")
                # Pick fastest lap
                selected_lap_number = int(valid_laps.sort_values(by="LapTime").iloc[0]["LapNumber"])

            lap_rows = laps[laps["LapNumber"] == selected_lap_number]
            if lap_rows.empty:
                raise ValueError(f"Lap {selected_lap_number} not found for driver {target_driver}")

            selected_lap = lap_rows.iloc[0]
            telemetry = selected_lap.get_car_data().add_distance().copy()

            if telemetry.empty:
                raise ValueError(f"No telemetry data for {target_driver} lap {selected_lap_number}")

            # Apply sector window filtering
            if sector_start is not None and sector_end is not None:
                telemetry = self._apply_sector_window(telemetry, sector_start, sector_end)

            # Apply stride
            if stride > 1:
                telemetry = telemetry.iloc[::stride]

            # Apply point limit
            if len(telemetry) > limit_points:
                downsample_step = max(1, math.ceil(len(telemetry) / limit_points))
                telemetry = telemetry.iloc[::downsample_step]

            # Normalize to rows
            telemetry_rows = self._telemetry_rows_from_frame(telemetry)

            return self._build_response(
                telemetry_rows,
                additional_meta={
                    "selected_lap": int(selected_lap_number),
                    "telemetry_points": len(telemetry_rows),
                },
                additional_filters={
                    "driver": target_driver,
                    "lap": selected_lap_number,
                    "limit_points": limit_points,
                    "stride": stride,
                    "sector_window": f"{sector_start}-{sector_end}" if sector_start else None,
                },
            )
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Telemetry extraction error: {str(exc)}")

    @staticmethod
    def _apply_sector_window(
        telemetry: pd.DataFrame, sector_start: int, sector_end: int
    ) -> pd.DataFrame:
        """Filter telemetry to specific sector window."""
        if sector_start is None or sector_end is None or telemetry.empty:
            return telemetry
        if "Distance" not in telemetry.columns:
            return telemetry

        max_distance = telemetry["Distance"].max()
        if pd.isna(max_distance) or max_distance <= 0:
            return telemetry

        sector_size = float(max_distance) / 3.0
        start_distance = (sector_start - 1) * sector_size
        end_distance = sector_end * sector_size
        return telemetry[(telemetry["Distance"] >= start_distance) & (telemetry["Distance"] <= end_distance)]

    @staticmethod
    def _telemetry_rows_from_frame(telemetry: pd.DataFrame) -> list[dict]:
        """Convert telemetry dataframe to normalized rows."""
        rows = []
        for _, row in telemetry.iterrows():
            rows.append(
                {
                    "time_seconds": DataNormalizer.to_time_seconds(row.get("Time"), precision=4),
                    "distance_m": DataNormalizer.to_float(row.get("Distance"), precision=3),
                    "speed_kph": DataNormalizer.to_float(row.get("Speed"), precision=2),
                    "throttle_pct": DataNormalizer.to_float(row.get("Throttle"), precision=2),
                    "brake": DataNormalizer.to_bool(row.get("Brake")),
                    "drs": DataNormalizer.to_bool(row.get("DRS")),
                    "rpm": DataNormalizer.to_int(row.get("RPM")),
                    "gear": DataNormalizer.to_int(row.get("nGear")),
                }
            )
        return rows


class WeatherExtractor(BaseDataExtractor):
    """Extract weather data for sessions."""

    def extract(self, include_per_lap: bool = False) -> dict:
        """
        Extract weather information.

        Args:
            include_per_lap: If True, align each weather snapshot to the nearest lap number;
                             else return the raw time-series from session.weather_data.
        """
        from api.services.extraction import extract_weather

        try:
            # Some session implementations (and test fakes) expose weather
            # under `.weather` instead of `.weather_data`. Support both names
            # for backward compatibility with partial sessions returned by
            # the runtime or test fixtures.
            weather = getattr(self.session, "weather_data", None)
            if weather is None:
                weather = getattr(self.session, "weather", None)
            if weather is None or weather.empty:
                raise ValueError("No weather data available for this session")

            rows = []
            if include_per_lap:
                # Merge weather snapshots to laps by nearest Time
                try:
                    laps = self.session.laps.copy()
                except Exception:
                    return self._build_response([])
                lap_time_col = "LapStartTime" if "LapStartTime" in laps.columns else "Time"
                laps = laps[laps[lap_time_col].notna()]

                if self.driver:
                    laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

                weather_sorted = weather.sort_values("Time").reset_index(drop=True)

                for _, lap in laps.iterrows():
                    lap_start = lap[lap_time_col]
                    # Find the weather row whose Time is closest to this lap's start
                    try:
                        time_deltas = (weather_sorted["Time"] - lap_start).abs()
                        nearest_idx = time_deltas.idxmin()
                        w = weather_sorted.iloc[nearest_idx]
                    except Exception:
                        continue

                    rows.append(
                        {
                            "lap_number": DataNormalizer.to_int(lap.get("LapNumber")),
                            "driver_code": DataNormalizer.to_str(lap.get("Driver")),
                            "track_temp_c": DataNormalizer.to_float(w.get("TrackTemp")),
                            "air_temp_c": DataNormalizer.to_float(w.get("AirTemp")),
                            "humidity_pct": DataNormalizer.to_float(w.get("Humidity")),
                            "wind_speed_ms": DataNormalizer.to_float(w.get("WindSpeed")),
                            "wind_direction_deg": DataNormalizer.to_float(w.get("WindDirection")),
                            "rainfall": DataNormalizer.to_bool(w.get("Rainfall")),
                        }
                    )
            else:
                # Return the full time-series of weather snapshots
                for _, w in weather.iterrows():
                    rows.append(
                        {
                            "lap_number": None,
                            "driver_code": None,
                            "time_seconds": DataNormalizer.to_time_seconds(w.get("Time")),
                            "track_temp_c": DataNormalizer.to_float(w.get("TrackTemp")),
                            "air_temp_c": DataNormalizer.to_float(w.get("AirTemp")),
                            "humidity_pct": DataNormalizer.to_float(w.get("Humidity")),
                            "wind_speed_ms": DataNormalizer.to_float(w.get("WindSpeed")),
                            "wind_direction_deg": DataNormalizer.to_float(w.get("WindDirection")),
                            "rainfall": DataNormalizer.to_bool(w.get("Rainfall")),
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows, additional_filters={"include_per_lap": include_per_lap})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Weather extraction error: {str(exc)}")


class PitStopExtractor(BaseDataExtractor):
    """Extract pit stop strategy and timing data."""

    def extract(self) -> dict:
        """Extract pit stop data for all drivers or specific driver."""
        from api.services.extraction import extract_pit_stops

        try:
            # Guard: if the session failed to load (e.g. data not yet available
            # from FastF1), surface a clean error instead of crashing deep inside
            # the FastF1 property accessor with a confusing DataNotLoadedError.
            load_error = getattr(self.session, "_load_error", None)
            if load_error is not None:
                raise Exception(
                    f"Session data not available (FastF1 load failed): {load_error}"
                )

            try:
                laps = self.session.laps.copy()
            except Exception:
                return self._build_response([])
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            rows = []
            has_pit_lap_columns = "PitInLap" in laps.columns and "PitOutLap" in laps.columns
            has_pit_time_columns = "PitInTime" in laps.columns and "PitOutTime" in laps.columns

            # Group by driver and extract pit stop info
            for driver_code, driver_laps in laps.groupby("Driver"):
                stop_num = 0
                for _, lap in driver_laps.sort_values("LapNumber").iterrows():
                    pit_in_lap = lap.get("PitInLap") if has_pit_lap_columns else None
                    pit_out_lap = lap.get("PitOutLap") if has_pit_lap_columns else None
                    pit_in_time = lap.get("PitInTime") if has_pit_time_columns else None
                    pit_out_time = lap.get("PitOutTime") if has_pit_time_columns else None

                    # Preferred indicator for FastF1 laps: PitInTime.
                    # FastF1 data sometimes has incomplete PitOutTime (NaT), so we detect on PitInTime alone.
                    # Fallback to PitInLap if timing columns are unavailable.
                    is_pit_stop = False
                    if has_pit_time_columns:
                        is_pit_stop = pd.notna(pit_in_time)
                    elif has_pit_lap_columns:
                        is_pit_stop = pd.notna(pit_in_lap)

                    if not is_pit_stop:
                        continue

                    stop_num += 1

                    # Derive lap_in/lap_out robustly when lap-based columns are missing.
                    derived_lap_number = DataNormalizer.to_int(lap.get("LapNumber"))
                    lap_in = DataNormalizer.to_int(pit_in_lap) if pd.notna(pit_in_lap) else derived_lap_number
                    lap_out = DataNormalizer.to_int(pit_out_lap) if pd.notna(pit_out_lap) else derived_lap_number

                    pit_duration_seconds = None
                    if pd.notna(pit_in_time) and pd.notna(pit_out_time):
                        try:
                            duration = (pit_out_time - pit_in_time).total_seconds()
                            # Validate: pit stop should be between 0 and 120 seconds (realistic range)
                            if 0 <= duration <= 120:
                                pit_duration_seconds = duration
                        except Exception:
                            pit_duration_seconds = None
                    elif pd.notna(lap.get("PitDuration")):
                        pit_duration_seconds = DataNormalizer.to_time_seconds(lap.get("PitDuration"), precision=2)

                    # Derive compound_out from the next lap (outlap shows new compound).
                    compound_out = None
                    try:
                        outlap_rows = driver_laps[driver_laps["LapNumber"] == derived_lap_number + 1]
                        if len(outlap_rows) > 0:
                            compound_out = str(outlap_rows.iloc[0].get("Compound")) if pd.notna(outlap_rows.iloc[0].get("Compound")) else None
                    except Exception:
                        compound_out = None

                    # Derive time_gain_loss_seconds from position delta before and after pit.
                    # Simple heuristic: estimate 0.3s per position (approximate pit gain/loss).
                    time_gain_loss_seconds = None
                    try:
                        pre_pit_rows = driver_laps[driver_laps["LapNumber"] == derived_lap_number - 1]
                        post_pit_rows = driver_laps[driver_laps["LapNumber"] == derived_lap_number + 2]
                        if len(pre_pit_rows) > 0 and len(post_pit_rows) > 0:
                            pre_pit_pos = pre_pit_rows.iloc[0].get("Position")
                            post_pit_pos = post_pit_rows.iloc[0].get("Position")
                            if pd.notna(pre_pit_pos) and pd.notna(post_pit_pos):
                                # Positive = position improved (negative seconds = gain), negative = position worsened (positive seconds = loss).
                                position_delta = pre_pit_pos - post_pit_pos
                                time_gain_loss_seconds = position_delta * 0.3  # 0.3s per position as rough estimate
                    except Exception:
                        time_gain_loss_seconds = None

                    rows.append(
                        {
                            "driver_code": str(driver_code),
                            "driver_number": DataNormalizer.to_int(lap.get("DriverNumber")),
                            "stop_number": stop_num,
                            "lap_in": lap_in,
                            "lap_out": lap_out,
                            "stop_duration_seconds": DataNormalizer.to_float(pit_duration_seconds, precision=2),
                            "compound_in": str(lap.get("Compound")) if pd.notna(lap.get("Compound")) else None,
                            "compound_out": compound_out,
                            "time_gain_loss_seconds": DataNormalizer.to_float(time_gain_loss_seconds, precision=2),
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Pit stop extraction error: {str(exc)}")


class IncidentExtractor(BaseDataExtractor):
    """Extract incidents, messages, and race events."""

    def extract(self, include_radio: bool = False) -> dict:
        """
        Extract race-control incidents from session.race_control_messages.

        Args:
            include_radio: Reserved for API compatibility; race_control_messages
                           does not carry radio rows, so this has no effect.
        """
        from api.services.extraction import extract_incidents

        try:
            messages = self.session.race_control_messages
            if messages is None or messages.empty:
                rows = []
            else:
                rows = []
                for _, msg in messages.iterrows():
                    flag = DataNormalizer.to_str(msg.get("Flag")) or "UNKNOWN"
                    scope = DataNormalizer.to_str(msg.get("Scope"))
                    message_type = flag.upper().replace(" ", "_")

                    drivers_involved = []
                    racing_number = msg.get("RacingNumber")
                    if pd.notna(racing_number):
                        drivers_involved.append(str(racing_number))

                    rows.append(
                        {
                            "lap_number": DataNormalizer.to_int(msg.get("Lap")),
                            "message_type": message_type,
                            "flag": flag,
                            "scope": scope,
                            "sector": DataNormalizer.to_int(msg.get("Sector")),
                            "drivers_involved": drivers_involved,
                            "message_text": DataNormalizer.to_str(msg.get("Message")) or "",
                            "timestamp_seconds": DataNormalizer.to_time_seconds(msg.get("Time")),
                            "impact_on_race": self._categorize_impact(flag),
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows, additional_filters={"include_radio": include_radio})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Incident extraction error: {str(exc)}")

    @staticmethod
    def _categorize_impact(flag: str) -> str:
        """Categorize race impact based on the Flag value from race_control_messages."""
        flag_upper = (flag or "").upper()
        if flag_upper in ("RED",):
            return "high"
        elif flag_upper in ("YELLOW", "DOUBLE YELLOW", "SAFETY CAR", "VIRTUAL SAFETY CAR", "VSC"):
            return "medium"
        elif flag_upper in ("GREEN", "CLEAR", "CHEQUERED"):
            return "low"
        return "unknown"


class PositionExtractor(BaseDataExtractor):
    """Extract position changes and gaps over race distance."""

    def extract(self, sample_interval: int = 5) -> dict:
        """
        Extract position and gap data.

        Args:
            sample_interval: Sample every N laps for position data
        """
        from api.services.extraction import extract_positions

        try:
            if sample_interval < 1:
                raise ValueError("sample_interval must be a positive integer")

            try:
                laps = self.session.laps.copy()
            except Exception:
                return self._build_response([], additional_filters={"sample_interval": sample_interval})
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            if laps.empty:
                return self._build_response([], additional_filters={"sample_interval": sample_interval})

            # Prepare numeric columns for derived race metrics.
            laps = laps.copy()
            laps["lap_seconds"] = laps["LapTime"].apply(
                lambda v: v.total_seconds() if hasattr(v, "total_seconds") else None
            )
            laps["position_num"] = pd.to_numeric(laps["Position"], errors="coerce")
            laps["lap_number_num"] = pd.to_numeric(laps["LapNumber"], errors="coerce")

            laps = laps.sort_values(["Driver", "lap_number_num"])
            laps["race_time_seconds"] = laps.groupby("Driver")["lap_seconds"].cumsum()
            laps["prev_position"] = laps.groupby("Driver")["position_num"].shift(1)

            # Fastest lap in session for each driver.
            driver_best = laps.groupby("Driver")["lap_seconds"].transform("min")
            laps["is_fastest_lap_overall"] = laps["lap_seconds"] == driver_best

            # Fastest lap among all drivers for a given lap number.
            lap_best = laps.groupby("lap_number_num")["lap_seconds"].transform("min")
            laps["is_fastest_lap_of_lap_number"] = laps["lap_seconds"] == lap_best

            rows = []
            lap_numbers = sorted(
                {
                    int(ln)
                    for ln in laps["lap_number_num"].dropna().tolist()
                }
            )

            if not lap_numbers:
                return self._build_response([], additional_filters={"sample_interval": sample_interval})

            # Sample laps at interval
            sampled_laps = [ln for ln in lap_numbers if ln % sample_interval == 0 or ln == lap_numbers[-1]]

            for lap_num in sampled_laps:
                lap_slice = laps[laps["lap_number_num"] == lap_num]
                if lap_slice.empty:
                    continue

                lap_slice = lap_slice.sort_values(["position_num", "race_time_seconds"], na_position="last")

                leader_time = None
                for _, leader_candidate in lap_slice.iterrows():
                    if pd.notna(leader_candidate.get("position_num")) and pd.notna(
                        leader_candidate.get("race_time_seconds")
                    ):
                        leader_time = float(leader_candidate["race_time_seconds"])
                        break

                prev_car_time = None

                # Get all drivers' positions at this lap
                for _, lap_row in lap_slice.iterrows():
                    driver_code = lap_row.get("Driver")

                    race_time = lap_row.get("race_time_seconds")
                    race_time = float(race_time) if pd.notna(race_time) else None

                    gap_to_leader = None
                    if leader_time is not None and race_time is not None:
                        gap_to_leader = race_time - leader_time

                    gap_to_ahead = None
                    if prev_car_time is not None and race_time is not None:
                        gap_to_ahead = race_time - prev_car_time

                    if race_time is not None:
                        prev_car_time = race_time

                    position_change = None
                    prev_position = lap_row.get("prev_position")
                    current_position = lap_row.get("position_num")
                    if pd.notna(prev_position) and pd.notna(current_position):
                        # Positive means positions gained relative to prior lap.
                        position_change = int(prev_position - current_position)

                    rows.append(
                        {
                            "driver_code": str(driver_code),
                            "driver_number": DataNormalizer.to_int(lap_row.get("DriverNumber")),
                            "lap_number": DataNormalizer.to_int(lap_num),
                            "position": DataNormalizer.to_int(current_position),
                            "position_change": position_change,
                            "gap_to_leader_seconds": DataNormalizer.to_float(gap_to_leader, precision=3),
                            "gap_to_ahead_seconds": DataNormalizer.to_float(gap_to_ahead, precision=3),
                            "stint": DataNormalizer.to_int(lap_row.get("Stint")),
                            "track_status": DataNormalizer.to_str(lap_row.get("TrackStatus")),
                            "lap_time_seconds": DataNormalizer.to_float(lap_row.get("lap_seconds"), precision=3),
                            "is_fastest_lap_overall": bool(
                                lap_row.get("is_fastest_lap_overall", False)
                            ),
                            "is_fastest_lap_of_lap_number": bool(
                                lap_row.get("is_fastest_lap_of_lap_number", False)
                            ),
                        }
                    )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows, additional_filters={"sample_interval": sample_interval})
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Position extraction error: {str(exc)}")


class DRSExtractor(BaseDataExtractor):
    """Extract DRS activation data."""

    def extract(self) -> dict:
        """Extract DRS activation by driver and lap."""
        from api.services.extraction import extract_drs

        try:
            try:
                laps = self.session.laps.copy()
            except Exception:
                return self._build_response([])
            laps = laps[laps["LapTime"].notna()]

            if self.driver:
                laps = laps[laps["Driver"].astype(str).str.upper() == self.driver]

            rows = []
            for _, lap in laps.iterrows():
                drs_available = "DRS" in lap and pd.notna(lap.get("DRS"))
                drs_activated = drs_available and DataNormalizer.to_bool(lap.get("DRS"))

                rows.append(
                    {
                        "driver_code": str(lap.get("Driver")),
                        "driver_number": DataNormalizer.to_int(lap.get("DriverNumber")),
                        "lap_number": DataNormalizer.to_int(lap.get("LapNumber")),
                        "drs_available": drs_available,
                        "drs_activated": drs_activated,
                        "gap_behind_seconds": None,  # Would need gap data
                        "performance_delta_ms": None,  # Would need delta calculation
                    }
                )

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"DRS extraction error: {str(exc)}")


class TrackStatusExtractor(BaseDataExtractor):
    """Extract track status timeline."""

    def extract(self) -> dict:
        """Extract track status changes (flags, safety car, etc)."""
        from api.services.extraction import extract_track_status

        try:
            track_status = self.session.track_status
            if track_status is None or track_status.empty:
                rows = []
            else:
                rows = []
                prev_status = None
                prev_lap = None

                for _, row in track_status.iterrows():
                    status = str(row.get("Status", "UNKNOWN"))
                    lap = DataNormalizer.to_int(row.get("Lap"))
                    time = row.get("Time")

                    if status != prev_status:
                        rows.append(
                            {
                                "lap_number": lap,
                                "status": status,
                                "status_duration_laps": None,  # Calculated from gaps
                                "cause": self._map_status_to_cause(status),
                                "affected_zone": None,
                            }
                        )
                        prev_status = status
                        prev_lap = lap

            if self.limit:
                rows = rows[: self.limit]

            return self._build_response(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise Exception(f"Track status extraction error: {str(exc)}")

    @staticmethod
    def _map_status_to_cause(status: str) -> Optional[str]:
        """Map status to likely cause."""
        status_lower = status.lower()
        if "yellow" in status_lower:
            return "Yellow flag incident"
        elif "red" in status_lower:
            return "Red flag incident"
        elif "safety" in status_lower:
            return "Safety car deployed"
        elif "virtual" in status_lower:
            return "Virtual safety car"
        return None


# Registry for extractor classes (used by the full-session unified endpoint).
# TelemetryExtractor is intentionally excluded here — telemetry is only
# available via its own dedicated endpoint (UnifiedTelemetryAPIView).
EXTRACTORS_MAP = {
    "telemetry": TelemetryExtractor,
    "weather": WeatherExtractor,
    "pit_stops": PitStopExtractor,
    "incidents": IncidentExtractor,
    "positions": PositionExtractor,
    "drs": DRSExtractor,
    "track_status": TrackStatusExtractor,
}
