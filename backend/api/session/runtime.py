"""FastF1 runtime setup shared across services.

During unit tests the environment variable `USE_FAKE_FASTF1` is set by
`f1_project.settings_test` to avoid network calls; in that case we import
`api.session.fake_fastf1` instead of the real `fastf1` package.
"""
from pathlib import Path
import os

USE_FAKE = os.environ.get("USE_FAKE_FASTF1") in ("1", "true", "True")

if USE_FAKE:
	# Import the lightweight fake implementation used in tests.
	from api.session import fake_fastf1 as fastf1  # type: ignore
else:
	import fastf1

	# Keep FastF1 downloads cached inside backend/ for faster repeated local requests.
	_CACHE_DIR = Path(__file__).resolve().parents[2] / "f1_cache"
	_CACHE_DIR.mkdir(parents=True, exist_ok=True)
	fastf1.Cache.enable_cache(str(_CACHE_DIR))

__all__ = ["fastf1"]
