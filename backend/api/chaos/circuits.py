"""Populate CircuitProfile: seed file (curated) + trackmap geometry (derived). Idempotent."""
from pathlib import Path

import yaml

from .models import CircuitProfile

SEED = Path(__file__).parent / "data" / "circuits.yaml"


def load_seed(path=SEED) -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["circuits"]


def geometry_fields(circuit_key) -> dict:
    """Length (m) and corner count from the newest TrackGeometry for this key; {} when there is none."""
    from api.trackmap.models import TrackGeometry  # read-only use of the trackmap app

    g = TrackGeometry.objects.filter(circuit_key=circuit_key).order_by("-year", "-id").first()
    if g is None:
        return {}
    dist = (g.points or {}).get("distance") or []
    return {"length_m": round(dist[-1], 1) if dist else None, "corners": len(g.corners or []) or None}


def populate_circuit_profiles(seed=None) -> int:
    n = 0
    for c in seed if seed is not None else load_seed():
        fields = {k: c[k] for k in ("name", "locations", "circuit_type", "circuit_key", "wall_proximity",
                                    "overtaking_index", "elevation_range_m", "sources") if k in c}
        if c.get("circuit_key") is not None:
            fields.update(geometry_fields(c["circuit_key"]))
        CircuitProfile.objects.update_or_create(slug=c["slug"], defaults=fields)
        n += 1
    return n
