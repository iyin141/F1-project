#!/usr/bin/env python
"""Verify Module F cache service layer."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.getcwd())
django.setup()

# Test imports
try:
    from api.services.cache import (
        build_cache_key,
        ttl_for,
        get_from_cache,
        set_in_cache,
        acquire_lock,
        release_lock,
    )
    print("✓ All cache service functions imported successfully")
except Exception as e:
    print(f"✗ Failed to import cache service: {e}")
    sys.exit(1)

# Test build_cache_key
try:
    key = build_cache_key(2024, 1, "R", "results")
    assert key == "f1:2024:1:R:results", f"Unexpected key format: {key}"
    print(f"✓ build_cache_key works: {key}")
except Exception as e:
    print(f"✗ build_cache_key failed: {e}")
    sys.exit(1)

# Test ttl_for with historical data
try:
    ttl_hist = ttl_for("weather", 2023)
    assert ttl_hist == 604_800, f"Historical TTL incorrect: {ttl_hist}"
    print(f"✓ ttl_for historical: {ttl_hist}s (7 days)")
except Exception as e:
    print(f"✗ ttl_for historical failed: {e}")
    sys.exit(1)

# Test ttl_for with current season data
try:
    from datetime import datetime
    current_year = datetime.now().year
    
    # Standings: 1 hr
    ttl_standings = ttl_for("standings", current_year)
    assert ttl_standings == 3_600, f"Standings TTL incorrect: {ttl_standings}"
    print(f"✓ ttl_for standings (current season): {ttl_standings}s (1 hr)")
    
    # Weather: 5 min
    ttl_weather = ttl_for("weather", current_year)
    assert ttl_weather == 300, f"Weather TTL incorrect: {ttl_weather}"
    print(f"✓ ttl_for weather (current season): {ttl_weather}s (5 min)")
    
    # Incidents: 120s
    ttl_incidents = ttl_for("incidents", current_year)
    assert ttl_incidents == 120, f"Incidents TTL incorrect: {ttl_incidents}"
    print(f"✓ ttl_for incidents (current season): {ttl_incidents}s (120s)")
    
    # Lock: 120s
    ttl_lock = ttl_for("lock", current_year)
    assert ttl_lock == 120, f"Lock TTL incorrect: {ttl_lock}"
    print(f"✓ ttl_for lock: {ttl_lock}s (120s)")
    
    # Task status: 10 min
    ttl_task = ttl_for("task_status", current_year)
    assert ttl_task == 600, f"Task status TTL incorrect: {ttl_task}"
    print(f"✓ ttl_for task_status: {ttl_task}s (10 min)")
    
except Exception as e:
    print(f"✗ ttl_for current season failed: {e}")
    sys.exit(1)

# Test set_in_cache and get_from_cache
try:
    test_key = "test_module_f"
    test_data = {"x": 1, "y": "test", "z": [1, 2, 3]}
    test_ttl = 60
    
    # Clear any existing value
    get_from_cache(test_key)  # Ensure key exists or doesn't
    
    # Set value
    set_in_cache(test_key, test_data, test_ttl)
    print(f"✓ set_in_cache executed: {test_key}")
    
    # Get value
    retrieved = get_from_cache(test_key)
    assert retrieved == test_data, f"Retrieved data mismatch: {retrieved} != {test_data}"
    print(f"✓ get_from_cache works: {retrieved}")
    
except Exception as e:
    print(f"✗ set_in_cache/get_from_cache failed: {e}")
    sys.exit(1)

# Test acquire_lock and release_lock
try:
    lock_key = "test_lock_key"
    
    # Acquire lock (should succeed first time)
    acquired = acquire_lock(lock_key, ttl=60)
    assert acquired is True, f"First lock acquire failed: {acquired}"
    print(f"✓ acquire_lock succeeded (first attempt)")
    
    # Try to acquire again (should fail - lock held)
    acquired_again = acquire_lock(lock_key, ttl=60)
    assert acquired_again is False, f"Second lock acquire should fail: {acquired_again}"
    print(f"✓ acquire_lock correctly blocked (already held)")
    
    # Release lock
    release_lock(lock_key)
    print(f"✓ release_lock succeeded")
    
    # Acquire again (should succeed now)
    acquired_after_release = acquire_lock(lock_key, ttl=60)
    assert acquired_after_release is True, f"Lock acquire after release failed: {acquired_after_release}"
    print(f"✓ acquire_lock succeeded after release")
    
    # Cleanup
    release_lock(lock_key)
    
except Exception as e:
    print(f"✗ acquire_lock/release_lock failed: {e}")
    sys.exit(1)

print("\n✅ Module F cache service layer verified successfully!")
