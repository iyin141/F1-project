"""Shared readiness helpers for service-level partial-data handling."""

from __future__ import annotations

_DATA_UNAVAILABLE_MARKERS = (
    "relevant api is not supported for this session",
    "data you are trying to access has not been loaded yet",
    "cannot load laps",
    "failed to load any schedule data",
)


def build_readiness(can_proceed, available_data, unavailable_data, message=None, warnings=None):
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": warnings if warnings is not None else ([] if can_proceed else ([message] if message else [])),
    }


def is_data_unavailable_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _DATA_UNAVAILABLE_MARKERS)


def classify_fastf1_exception(exc: Exception, *, year: int, round_number: int, session_name: str, required_data: tuple[str, ...]):
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
