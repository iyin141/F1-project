"""
Shared readiness helpers for partial-data handling across all domains.

Every API response includes a readiness dict so the frontend can gracefully
handle missing data without crashing the UI.
"""
from __future__ import annotations

from datetime import datetime


# Markers in FastF1 exception messages indicating data is genuinely unavailable
# (as opposed to a transient error).
_DATA_UNAVAILABLE_MARKERS = (
    "relevant api is not supported for this session",
    "data you are trying to access has not been loaded yet",
    "cannot load laps",
    "failed to load any schedule data",
    "datanotloadederror",
)


def build_readiness(
    can_proceed: bool,
    available_data: list[str],
    unavailable_data: list[str],
    message: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """
    Build the standard readiness dict included in every API response.

    Parameters
    ----------
    can_proceed : bool
        Whether the frontend has enough data to render.
    available_data : list[str]
        Names of data types that were successfully loaded.
    unavailable_data : list[str]
        Names of data types that could not be loaded.
    message : str | None
        Human-readable summary (typically set when can_proceed is False).
    warnings : list[str] | None
        Explicit warnings list. When None, auto-derived from message.
    """
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": warnings if warnings is not None else (
            [] if can_proceed else ([message] if message else [])
        ),
    }


def ensure_payload_meta_checklist(
    payload: dict,
    available_defaults: list[str] | None = None,
    unavailable_defaults: list[str] | None = None,
) -> dict:
    """
    Ensure the payload's ``meta`` dict contains readiness fields.

    If the meta already has ``can_proceed``, ``available_data``, and
    ``unavailable_data``, the payload is returned unchanged. Otherwise the
    readiness fields are injected based on ``row_count`` and the provided
    defaults.
    """
    available_defaults = available_defaults or []
    unavailable_defaults = unavailable_defaults or []
    if not isinstance(payload, dict):
        return payload

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return payload

    if "can_proceed" in meta and "available_data" in meta and "unavailable_data" in meta:
        return payload

    row_count = meta.get("row_count", 0)
    can_proceed = bool(row_count) and not bool(unavailable_defaults)
    message = meta.get("message")
    if not can_proceed and not message:
        if unavailable_defaults:
            message = f"Session loaded, but required data is unavailable. Missing: {', '.join(unavailable_defaults)}."
        else:
            message = "No data available for the requested dataset."
    meta.update(
        build_readiness(
            can_proceed=can_proceed,
            available_data=available_defaults if can_proceed else [],
            unavailable_data=[] if can_proceed else (unavailable_defaults or available_defaults),
            message=None if can_proceed else message,
            warnings=[] if can_proceed else ([message] if message else []),
        )
    )
    return payload


def is_data_unavailable_error(exc: Exception) -> bool:
    """Return True if the exception indicates data is genuinely unavailable."""
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _DATA_UNAVAILABLE_MARKERS)


def classify_fastf1_exception(
    exc: Exception,
    *,
    year: int,
    round_number: int,
    session_name: str,
    required_data: tuple[str, ...],
) -> dict | None:
    """
    Classify a FastF1 exception as a readiness failure if applicable.

    Returns a readiness dict if the exception matches a known unavailability
    marker, or None if the exception should be raised normally.
    """
    if not is_data_unavailable_error(exc):
        return None

    missing = list(required_data) if required_data else ["session data"]
    message = (
        f"Session data is unavailable for {year} Round {round_number} ({session_name}). "
        f"Missing required data: {', '.join(missing)}."
    )

    detail = str(exc).strip()
    if detail:
        message = f"{message} Details: {detail}"

    return build_readiness(False, [], missing, message, [message])
