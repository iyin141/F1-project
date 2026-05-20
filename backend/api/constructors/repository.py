"""Repository layer for constructor standings — all ORM queries live here."""
from __future__ import annotations

import logging
import time

from api.models import ConstructorStandings
from api.common.request_id import get_request_id

logger = logging.getLogger(__name__)


def get_persisted_constructor_standings(year: int) -> list[dict] | None:
    """Return the persisted constructor standings list for a given year, or None."""
    logger.info(
        "event=db_check_start",
        extra={
            "request_id": get_request_id(),
            "table": "ConstructorStandings",
            "year": year,
        },
    )
    start_time = time.time()
    record = ConstructorStandings.objects.filter(year=year).first()
    duration_ms = (time.time() - start_time) * 1000
    
    hit = record is not None
    rows_data = record.payload.get("standings", []) if record else []
    rows = len(rows_data)
    
    logger.info(
        "event=db_check_complete",
        extra={
            "request_id": get_request_id(),
            "table": "ConstructorStandings",
            "hit": hit,
            "rows": rows,
            "duration_ms": f"{duration_ms:.1f}",
        },
    )
    
    return rows_data if rows_data else None
