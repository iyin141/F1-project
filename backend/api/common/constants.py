"""
Shared constants used across multiple API domains.
"""
from __future__ import annotations

# Shared HTTP headers for all Ergast/Jolpica API calls.
JOLPICA_HEADERS = {
    "User-Agent": "f1-project/1.0 (Django backend)",
    "Accept": "application/json",
}

# Default timeout for external API requests (seconds).
JOLPICA_TIMEOUT = 20

# FastF1 telemetry is only available from 2018 onwards.
TELEMETRY_MIN_YEAR = 2018


def clean_session_type(raw: str | None) -> str:
    """
    Normalize various session name inputs into canonical codes used across the app.

    Examples:
        None -> 'R'
        'race' -> 'R'
        'qualifying' -> 'Q'
        'practice 1' -> 'FP1'
        'sprint_shootout' -> 'SQ'
    """
    if raw is None:
        return "R"
    s = str(raw).strip().lower()
    if s in ("r", "race", "races"):
        return "R"
    if s in ("q", "qualifying", "qual"):
        return "Q"
    if s in ("s", "sprint"):
        return "S"
    if "sprint" in s and "shootout" in s:
        return "SQ"
    if "sprint_shootout" in s or s == "sq":
        return "SQ"
    if "practice" in s:
        # practice 1/2/3 -> FP1/FP2/FP3
        if "1" in s:
            return "FP1"
        if "2" in s:
            return "FP2"
        return "FP3"
    return "R"
