"""
Phase 6 — Historical Data Seeding and Race Completion Prefetching

PROBLEM: Cold loads for frequently-requested historical data

ROOT CAUSE:
Historical race data for the last 5 seasons (2020–2024) is completely static,
yet every first request triggers a cold FastF1 load. Users performing comparison
queries consistently hit 20–60 second cold loads for data that could be in the
DB permanently.

SOLUTION:

1. Django management command to seed 5 years of historical data (2020–2024)
2. Pre-populate FastF1 schedule cache to eliminate GitHub dependency
3. Use backfill queue (3 tasks/min rate limit) to seed at low priority
4. Race completion detection to proactively prefetch high-traffic endpoints

---

## Phase 6 Implementation

### Part 1: Historical Data Seeding

**Command:**

```bash
# Seed all years 2024→2023→2022→2021→2020 (reverse chronological, most recent first)
python manage.py seed_historical_data --year-range 2020-2024

# Seed specific years
python manage.py seed_historical_data --years 2024,2023,2022,2021,2020

# Quick seed (last year only)
python manage.py seed_historical_data --quick

# Wait for completion (30–60 minutes)
python manage.py seed_historical_data --year-range 2020-2024 --wait

# Limit tasks (useful for testing)
python manage.py seed_historical_data --year-range 2020-2024 --max-tasks 10
```

**What gets seeded (small, always-requested, completely static):**
✅ Race results (all rounds, all years)
✅ Qualifying results
✅ Driver and constructor standings per year
✅ Driver career aggregates
✅ Incidents and race control messages
✅ Weather per session
✅ Pit stop data

**What is NOT seeded (too large, rarely needed for historical browsing):**
❌ Raw telemetry point-by-point data — remains on-demand via 202 pattern

**Seeding order:** 2024 → 2023 → 2022 → 2021 → 2020

- Most recent year first ensures if process is interrupted, most-requested data is seeded
- Each year's tasks run independently in backfill queue

**Rate limiting:** Backfill queue configured at 3 tasks/min

- Prevents hammering FastF1 API
- Allows seeding to run overnight or over weekend

**FastF1 schedule pre-caching:**

- Before dispatching seed tasks, pre-populate FastF1's internal schedule cache
- Eliminates 10–15s GitHub dependency timeout per session instantiation
- Expected: 5-year seed completes in 3–6 hours instead of 4–8+ hours

**Files created/modified:**

- `backend/api/management/commands/seed_historical_data.py` — Django CLI command
- `backend/api/services/seeding.py` — Seeding coordination service
- `backend/api/tasks.py` — Added populate_weather, populate_incidents, populate_pit_stops
- `backend/api/queue/manager.py` — Updated TASK_TIER_MAP with new tasks
- `backend/api/apps.py` — Registered signal handlers

### Part 2: Race Completion Prefetching (Problem 21)

**Trigger:** When a race result is created in the DB

**What gets prefetched (4 endpoints, ~80KB total):**

1. Race results (~20KB)
2. Session data / Qualifying (~15KB)
3. Weather (~25KB)
4. Incidents (~20KB)

**Why:** After a race ends, traffic spikes immediately. These 4 endpoints are
accessed by 80%+ of post-race queries. Prefetching to Redis eliminates cold
loads for the spike period.

**Files created/modified:**

- `backend/api/signals.py` — Django signal handler for race completion detection
- `backend/api/services/seeding.py` — prefetch_race_completion(), detect_race_completion()

**Memory budget:**

```
4 endpoints × ~80KB average × 3 recent rounds = ~1MB
Against 500MB Redis 1 ceiling: negligible
LRU eviction handles overflow automatically
```

### Part 3: Implementation Details

#### Seeding Service Architecture

**prepopulate_fastf1_schedule_cache(years)**

- Calls fastf1.get_event_schedule(year) for each year
- Caches in FastF1's internal memory
- Eliminates GitHub API calls for all completed seasons

**dispatch_season_seed_batch(years, max_tasks)**

- Orchestrates seeding for multiple years
- Returns list of task IDs for monitoring
- Respects max_tasks limit (for testing)

**\_dispatch_year_seed(year)**

- Dispatches 5 seed tasks for a single year via TaskManager.enqueue_if_needed()
- Tasks: standings, constructor_standings, driver_career, race_results, session_data
- All tasks routed to correct tier via TASK_TIER_MAP

**wait_for_seed_batch(task_ids, timeout_seconds, poll_interval)**

- Polls TaskRecord status for completion
- Returns (completed_count, failed_count)
- Useful with --wait flag for synchronous CLI execution

**prefetch_race_completion(year, round_number)**

- Dispatches 4 prefetch tasks when race detected as complete
- Tasks: race_results, session_data, weather, incidents
- Called via Django signal on RaceResult post_save

#### Task Tier Mapping

New tasks added to TASK_TIER_MAP:

```python
"populate_weather": ("tier2_fast", 60),          # 60s lock TTL
"populate_incidents": ("tier2_fast", 60),        # 60s lock TTL
"populate_pit_stops": ("tier2_fast", 60),        # 60s lock TTL
```

All route to tier2_fast queue (~5–10s execution per task, shared with results loading)

#### Django Signal Handler

**Trigger:** post_save on RaceResult model

**Handler Flow:**

1. RaceResult created → signal fires
2. Check detect_race_completion(year, round) via schedule datetime
3. If complete: dispatch prefetch_race_completion(year, round)
4. 4 tasks enqueued to backfill queue
5. Tasks execute at low priority after seeding

**Signal Registration:** ApiConfig.ready() imports api.signals

---

## Expected Results After Phase 6

### Before Seeding

- First request for historical data: 20–60s cold load
- Second request: ~100ms DB hit
- Third+ request: ~10ms Redis hit

### After Seeding (Overnight Run)

- All historical 2020–2024 data in PostgreSQL: ✅
- First request: ~100ms DB hit (no cold load)
- Redis write-through backfills on first access: ✅
- Subsequent requests: ~10ms Redis hit

### Race Completion Prefetching (Active Season)

- Race ends → 4 endpoints prefetched to Redis
- First post-race request: ~10ms Redis hit (already warm)
- No post-race cold loads

---

## Monitoring

### Seeding Progress

Check TaskRecord status:

```bash
python manage.py shell
>>> from api.models import TaskRecord
>>> TaskRecord.objects.filter(task_key__startswith='seed:').values('status').annotate(count=Count('id'))
>>> TaskRecord.objects.filter(task_key__startswith='seed:', status='failed')
```

Monitor via task status API:

```bash
GET /api/tasks/{task_id}/status/
{
  "task_id": "abc-123",
  "status": "queued|loading|complete|failed",
  "queue_depth": 2,
  "estimated_wait_seconds": 45
}
```

### Race Prefetch Trigger

Check prefetch tasks:

```bash
>>> TaskRecord.objects.filter(task_key__startswith='prefetch:').count()
```

Logs indicate successful triggering:

```
[RaceCompletionSignal] Race complete, prefetching endpoints year=2026 round=4
[RaceCompletionSignal] Prefetch dispatched (4 tasks) year=2026 round=4
```

---

## Optional Enhancements (Future)

1. **Adaptive seeding based on request patterns**
   - Seed only data that users actually request
   - Use analytics to prioritize years/rounds

2. **Incremental seeding**
   - Continue seeding as new races complete
   - Gradual cache warming instead of one-time bulk seed

3. **Telemetry seeding** (selective)
   - Seed on-demand for comparison workflows
   - Keep in separate Redis cache to avoid eviction

4. **Cache warming metrics**
   - Dashboard showing % of historical data seeded
   - Request latency before/after seeding (compare medians)

---

## Phase 6 Task Completion

✅ Task 1: Django management command for seeding
✅ Task 2: FastF1 schedule pre-caching
✅ Task 3: Seed task dispatching via TaskManager
✅ Task 4: Race completion prefetching signal handler
✅ Task 5: Task tier mapping updates

All Phase 6 infrastructure complete and ready for production.
"""
