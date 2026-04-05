"""FastF1 runtime setup shared across services."""
from pathlib import Path

import fastf1

# Keep FastF1 downloads cached inside backend/ for faster repeated local requests.
_CACHE_DIR = Path(__file__).resolve().parents[2] / "f1_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
fastf1.Cache.enable_cache(str(_CACHE_DIR))

__all__ = ["fastf1"]
