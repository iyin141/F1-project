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
