"""Repository layer for constructor standings — all ORM queries live here."""
from __future__ import annotations

from api.models import ConstructorStandings


def get_persisted_constructor_standings(year: int) -> list[dict] | None:
    """Return the persisted constructor standings list for a given year, or None."""
    record = ConstructorStandings.objects.filter(year=year).first()
    if record is None:
        return None
    rows = record.payload.get("standings", [])
    return rows if rows else None
