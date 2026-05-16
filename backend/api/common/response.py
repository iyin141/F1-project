"""
Shared response builders used across all API domains.

These helpers standardise the error and unavailable-data response shapes
so every endpoint returns a consistent contract.
"""
from __future__ import annotations

from datetime import datetime


def build_error_payload(domain: str, message: str, code: str) -> dict:
    """
    Build a standardised error response dict.

    Parameters
    ----------
    domain : str
        Dot-separated identifier, e.g. ``"analysis.laps"``.
    message : str
        Human-readable error description.
    code : str
        Machine-readable error code, e.g. ``"ANALYSIS_LAPS_ERROR"``.
    """
    return {
        "error": f"{domain} error: {message}",
        "error_code": code,
    }


def build_unified_unavailable_response(
    year: int,
    round_number: int,
    session_name: str,
    unavailable_type: str,
    detail_message: str,
    driver: str | None = None,
    limit: int | None = None,
) -> dict:
    """
    Build the standard "data unavailable" response for unified-service endpoints.

    Used when a FastF1 session loads successfully but a specific data type
    (e.g. weather, incidents) is not available for this session.
    """
    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": str(session_name).upper(),
            "row_count": 0,
            "extracted_at": datetime.now().isoformat(),
            "limit_max": 2000,
            "can_proceed": False,
            "available_data": [],
            "unavailable_data": [str(unavailable_type)],
            "message": detail_message,
            "warnings": [detail_message],
        },
        "filters_applied": {
            "driver": str(driver).upper() if driver else None,
            "limit": limit,
        },
        "data": [],
    }
