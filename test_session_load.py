"""
Controlled test: Load 2025 Round 19 Race with debug logging.
Run this on BOTH machines (local + Oracle) to compare results.

Usage:
  python test_session_load.py
"""
import os
import sys

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Set Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")

import fastf1
import logging

# Full debug output
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
fastf1.set_log_level('DEBUG')

# Use a FRESH temp cache so we're not reading poisoned data
import tempfile
fresh_cache = os.path.join(tempfile.gettempdir(), "f1_test_cache_clean")
os.makedirs(fresh_cache, exist_ok=True)
fastf1.Cache.enable_cache(fresh_cache)

print(f"\n{'='*60}")
print(f"Cache dir: {fresh_cache}")
print(f"Proxy env: HTTP_PROXY={os.environ.get('HTTP_PROXY', 'NOT SET')}")
print(f"Proxy env: HTTPS_PROXY={os.environ.get('HTTPS_PROXY', 'NOT SET')}")
print(f"{'='*60}\n")

# Test: 2025 Round 19 Race
year, round_num, session_type = 2025, 19, 'R'
print(f"Loading session: {year} Round {round_num} {session_type}")

try:
    session = fastf1.get_session(year, round_num, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    
    laps = session.laps
    print(f"\n{'='*60}")
    print(f"SUCCESS! Loaded {len(laps)} laps")
    print(f"Drivers: {sorted(laps['Driver'].unique().tolist()) if len(laps) > 0 else 'NONE'}")
    print(f"{'='*60}")
except Exception as e:
    print(f"\n{'='*60}")
    print(f"FAILED: {type(e).__name__}: {e}")
    print(f"{'='*60}")
