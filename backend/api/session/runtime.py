"""FastF1 runtime setup shared across services.

During unit tests the environment variable `USE_FAKE_FASTF1` is set by
`f1_project.settings_test` to avoid network calls; in that case we import
`api.session.fake_fastf1` instead of the real `fastf1` package.
"""
import os
from pathlib import Path
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Guarantee .env is loaded before we try to read proxy variables,
# in case this file is imported before Django's settings.py finishes.
load_dotenv()

# ── Proxy Setup ───────────────────────────────────────────────
# Set BEFORE importing fastf1 so requests use it globally
proxy_host = os.environ.get("PROXY_HOST")
if proxy_host:
    proxy_user = os.environ.get("PROXY_USER", "")
    proxy_pass = os.environ.get("PROXY_PASS", "")
    proxy_port = os.environ.get("PROXY_PORT", "8080")
    
    if proxy_user and proxy_pass:
        proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
        # Log safely without password
        logger.info(f"FastF1 proxy configured via environment variables. Host: {proxy_host}:{proxy_port} (Auth: YES)")
    else:
        proxy_url = f"http://{proxy_host}:{proxy_port}"
        logger.info(f"FastF1 proxy configured via environment variables. Host: {proxy_host}:{proxy_port} (Auth: NO)")
        
    os.environ['HTTPS_PROXY'] = proxy_url
    os.environ['HTTP_PROXY'] = proxy_url
    
    # Verify proxy works and log the IP being used
    try:
        import requests
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip_data = ip_resp.json()
        logger.info(f"PROXY VERIFIED: Traffic is successfully routing through IP: {ip_data.get('ip')}")
    except Exception as e:
        logger.error(f"PROXY VERIFICATION FAILED: Could not route traffic through proxy: {e}")

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

	# Ergast was shut down in Nov 2024 and blocks datacenter/proxy IPs for older data.
	# FastF1 3.x still tries to call it during session.load(), and when it fails with
	# an AttributeError it can prevent the internal _data_loaded flag from being set,
	# causing DataNotLoadedError false negatives on session.laps even after a successful load.
	# Patching it out is safe — the supplementary first-lap-time data it provides
	# is not used by any of our extractors.
	fastf1.core.Session._add_first_lap_time_from_ergast = lambda self: None
	logger.info("FastF1 Ergast supplement patched out (defunct API, not used by extractors).")

__all__ = ["fastf1"]
