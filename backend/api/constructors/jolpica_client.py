"""Jolpica/Ergast HTTP client for constructor standings."""
from __future__ import annotations

import logging
import requests

from api.common.constants import JOLPICA_HEADERS, JOLPICA_TIMEOUT

logger = logging.getLogger(__name__)

API_URLS = [
    "https://ergast.com/api/f1/{year}/constructorStandings.json",
    "https://api.jolpi.ca/ergast/f1/{year}/constructorStandings.json",
]


def fetch_constructor_standings(year: int) -> dict | None:
    """
    Try each API URL in order and return the raw JSON response dict,
    or None if all fail.
    """
    last_error = None
    for template in API_URLS:
        url = template.format(year=year)
        try:
            response = requests.get(url, headers=JOLPICA_HEADERS, timeout=JOLPICA_TIMEOUT)
            if response.status_code == 200:
                return response.json()
            last_error = f"{url} returned status {response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{url} failed: {exc}"

    logger.warning("event=constructor_api_unavailable year=%s error=%s", year, last_error)
    return None
