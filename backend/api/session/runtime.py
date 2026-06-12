"""FastF1 runtime setup shared across services.

During unit tests the environment variable `USE_FAKE_FASTF1` is set by
`f1_project.settings_test` to avoid network calls; in that case we import
`api.session.fake_fastf1` instead of the real `fastf1` package.
"""
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ── Proxy Setup ───────────────────────────────────────────────
# Set BEFORE importing fastf1 so requests use it globally
proxy_host = os.environ.get("PROXY_HOST")
if proxy_host:
    proxy_user = os.environ.get("PROXY_USER", "")
    proxy_pass = os.environ.get("PROXY_PASS", "")
    proxy_port = os.environ.get("PROXY_PORT", "8080")
    
    if proxy_user and proxy_pass:
        proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
    else:
        proxy_url = f"http://{proxy_host}:{proxy_port}"
        
    os.environ['HTTPS_PROXY'] = proxy_url
    os.environ['HTTP_PROXY'] = proxy_url
    logger.info("FastF1 proxy configured via environment variables.")

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
