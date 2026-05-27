# F1 API — Performance Optimization Prompt
> Django + FastF1 + Celery + Redis + PostgreSQL
> Use this prompt in full with Claude or any LLM to get architecture-level fixes.

---

## Context

You are helping optimize a production Django REST API that wraps FastF1, a Python library
for Formula 1 telemetry and race data. The stack is:

- **Web server**: Django + Gunicorn (sync workers)
- **Task queue**: Celery with Redis as broker and result backend
- **Cache**: Redis (via django-redis)
- **Database**: PostgreSQL
- **Data source**: FastF1 (Python lib that calls the official F1 API and caches locally)
- **Session loading**: `session.load()` fetches laps, telemetry, weather, and messages
- **Persistence flow**: request → FastF1 load → return response → Celery task writes to DB
- **Current problems**:
  - Responses range from 2.5s (incidents) to 67s (weather with GitHub timeouts)
  - Every client request hits a 301 redirect before the 200
  - In-flight duplicate FastF1 loads are uncontrolled — same session loads 3× simultaneously
  - Gunicorn sync workers block entirely during FastF1 loads
  - No bounded cache — loaded data accumulates in memory indefinitely
  - Single Celery queue — telemetry jobs (60s+, 100MB) block standings lookups (50ms)
  - No dedicated worker pools — 10 concurrent requests cause worker starvation
  - FastF1 fetches the F1 schedule from GitHub on every session instantiation,
    adding 10–15s dead time when the GitHub connection times out or resets

All answers must be **theoretical architecture only — no code**.
For each problem provide:
1. Root cause (1–2 sentences)
2. Proposed fix (detailed theoretical description)
3. Edge cases / failure modes to watch
4. Priority: critical / high / medium / low

---

## PART 1 — FastF1-Specific Problems

---

### PROBLEM 1 — FastF1 over-loading (selective session.load flags)

**Root cause**
Every endpoint calls `session.load()` with all four flags enabled (laps, telemetry, weather,
messages) regardless of what the endpoint actually needs. Weather data alone triggers a
full session load including 50–100MB of lap and telemetry data, which is why
`unified/weather` endpoints take 28–67 seconds while incidents take 2–3 seconds.

**Fix**
Design a loading profile system at the SessionManager layer. Each endpoint category
declares a named profile that maps to the minimal set of FastF1 load flags needed:

- Weather endpoint → `weather=True, laps=False, telemetry=False, messages=False`
- Incidents endpoint → `messages=True, laps=False, telemetry=False, weather=False`
- Lap / pace / sector / stint analysis → `laps=True, telemetry=False, weather=False, messages=False`
- Telemetry endpoints → `laps=True, telemetry=True, weather=False, messages=False`
- Results endpoints → `laps=False, telemetry=False, weather=False, messages=False`
  (uses `session.results` which loads with session_info and driver_info only)
- Unified full-session → merged flags from all requested `include=` types

The SessionManager accepts a profile name, derives the flag set, and calls
`session.load()` with only those flags. The profile is declared at the service
layer and passed down — no endpoint calls `session.load()` directly.

For unified endpoints that accept `include=weather,incidents`, the manager merges
flag sets via logical OR: `weather=True` OR `messages=True` →
`{weather: True, messages: True, laps: False, telemetry: False}`.

**Edge cases**
- FastF1 internally mixes data streams during load; some endpoints (e.g. laps) silently
  depend on session_info and driver_info even when those flags aren't exposed. Treat these
  as always-on base dependencies that every profile includes automatically.
- If a profile requests laps but telemetry is needed later in the same request, the session
  object won't have telemetry data. The SessionManager must validate that the loaded
  profile satisfies all data access patterns for the endpoint before returning.

**Priority**: Critical — direct cause of the 28–67s weather and incidents response times.

---

### PROBLEM 2 — No live cache (write-through Redis pattern)

**Root cause**
The current flow is: DB miss → FastF1 load → return response → Celery writes to DB.
A second request arriving during the FastF1 load finds no DB entry, triggers another
full FastF1 load, and both requests race. Logs confirm the same session loading 3×
simultaneously. There is no intermediate layer between FastF1 and the DB to serve
concurrent requests.

**Fix**
Introduce a write-through Redis live cache as the intermediate layer:

**Read priority chain** (every endpoint checks in this order):
1. Redis cache → key: `session:{year}:{round}:{session}:{data_type}` → return 200 immediately
2. PostgreSQL DB → found → backfill Redis → return 200
3. Both miss → enqueue Celery task → set Redis lock → return 202 with task ID
   (views never call FastF1 directly — see Problem 12)

**In-flight deduplication**:
When a Celery task begins a FastF1 load, it atomically sets a lock key in Redis:
`session_loading:{year}:{round}:{session}:{data_type}` with a short TTL (90–120 seconds).
Any concurrent request that finds this lock returns a 202 referencing the same existing
task ID rather than enqueuing a duplicate. Use Redis `SETNX` for atomic lock acquisition.

**TTL strategy — every key must have a TTL, no exceptions**
Because all keys carry a TTL, `allkeys-lru` is the correct Redis eviction policy.
Redis evicts least recently used keys under memory pressure with zero OOM risk:

| Data type | TTL | Rationale |
|-----------|-----|-----------|
| Historical completed season (>1 year ago) | 7 days | Final data, rarely accessed |
| Current season completed race | 6–12 hours | Final data, frequently accessed |
| Current season in-progress race | 60–120 seconds | Updates during live session |
| Weather / track status | 5 minutes | Changes frequently mid-session |
| Qualifying results | 4 hours | Final after session ends |
| Driver / constructor standings | 1 hour | Updates only after each race |
| In-flight lock keys | 90–120 seconds | Must exceed max FastF1 load duration |
| Task status keys | 10 minutes | Only needed during client polling |
| Telemetry traces | 30 minutes | Burst-accessed then cold — see Problem 19 |

**Edge cases**
- If a FastF1 load fails after acquiring the lock, release the lock immediately rather
  than waiting for TTL expiry — otherwise all concurrent requests queue behind a dead
  lock for up to 120 seconds
- Redis eviction under memory pressure may silently remove a key mid-request. The read
  chain must fall through to DB gracefully — never treat a missing key as an error
- Keep the app cache Redis instance separate from the Celery broker Redis instance so
  a broker restart during deployment does not clear the response cache
- Telemetry data lives in a separate Redis database from the main app cache — see
  Problem 19 for the dedicated telemetry cache design

**Priority**: Critical — eliminates duplicate in-flight loads and is the architectural
foundation for all other caching and non-blocking view improvements.

---

### PROBLEM 3 — Single Celery queue causing worker starvation

**Root cause**
All tasks — from a 50ms standings lookup to a 60s telemetry parse — compete for the
same worker pool. A single telemetry job occupies a worker for a full minute while fast
tasks queue behind it. With 10 concurrent requests arriving simultaneously, slow tasks
starve fast ones and the entire system degrades regardless of how many workers are added.
This is a fundamental architectural problem, not a worker count problem.

**Fix**
Replace the single queue with four dedicated queues, each with its own worker pool
sized to its workload class. Tasks are classified by duration and memory footprint:

**Queue classification by workload tier**:

```
TIER 1 — Instant (< 500ms, low memory)
  Queue: tier1_instant | Workers: 8–10 | Prefetch: 4
  Tasks: populate_standings, populate_career, populate_schedule,
         populate_race_detail, driver/constructor API fetches
  Memory per worker: ~50MB
  Notes: Pure DB reads or small external API calls. No FastF1. High concurrency safe.

TIER 2 — Fast (500ms – 5s, moderate memory)
  Queue: tier2_fast | Workers: 4–6 | Prefetch: 2
  Tasks: populate_results, populate_qualifying, populate_weather,
         populate_incidents, populate_pit_stops, populate_track_status
  Memory per worker: ~200MB
  Notes: DB-first with minimal FastF1 load profiles (weather-only, messages-only).

TIER 3 — Medium (5s – 15s, higher memory)
  Queue: tier3_medium | Workers: 3–4 | Prefetch: 1
  Tasks: populate_laps, populate_pace, populate_stints, populate_sectors,
         populate_positions, populate_drs, populate_tyre_strategy
  Memory per worker: ~400MB
  Notes: Requires laps=True profile. Lower concurrency to avoid memory pressure.

TIER 4 — Heavy / Telemetry (15s – 60s+, highest memory)
  Queue: tier4_telemetry | Workers: 2 (hard limit) | Prefetch: 1
  Tasks: populate_telemetry_snapshot, populate_telemetry_overlay,
         populate_telemetry_compare, populate_telemetry_grid
  Memory per worker: ~800MB–1GB
  Concurrency: 1 per worker — no parallel telemetry within a worker
  ack_late: True — do not acknowledge until task completes
  Notes: See Problem 19 for full telemetry queue and cache design.

BACKFILL — Historical seeding (background, lowest priority)
  Queue: backfill | Workers: 2 | Prefetch: 1
  Tasks: all 5-year historical seeding tasks
  Rate limit: 3 tasks per minute (avoid hammering FastF1 API)
  Priority: lowest — never competes with live request queues
  Notes: Run overnight/weekend. Seed 2024→2023→2022→2021→2020 in priority order.
         Must be isolated from live queues — a backfill run must not consume workers
         needed during a live race weekend.
```

**Task routing**
Every task declares its queue at definition time via the task's `queue` attribute.
The classification is fixed — a telemetry task always routes to `tier4_telemetry`
regardless of call site. Organising tasks into domain folders (as per the restructure
prompt) makes this automatic when the routing is defined at the module level.

**Parallel dispatch within a tier**
For a session requiring multiple data types to be persisted, dispatch all independent
tasks as a Celery `group()` simultaneously within the appropriate tier. Race results,
qualifying, weather, and incidents are all tier2 tasks with no DB dependencies on each
other and persist in parallel. The group dispatches after the Redis write-through so
the cache is always populated before any DB write begins.

**Task deduplication across all queues**
Before enqueueing any task in any tier, check a Redis lock key:
`task_lock:{queue}:{data_type}:{year}:{round}:{session}`.
If the lock exists, return the existing Celery AsyncResult instead of creating a
duplicate. This is the SETNX pattern applied uniformly across all queues.
Lock TTLs must exceed expected task duration per tier:
- Tier 1: 30s lock TTL
- Tier 2: 60s lock TTL
- Tier 3: 90s lock TTL
- Tier 4: 180s lock TTL (telemetry can take 60s+ on cold load)

**Completion coordinator**
A parent task using Celery `chord()` (group + callback) marks a session as fully
persisted only when all child tasks in the group succeed. Failed children retry
independently without re-running siblings. Set a hard timeout per tier so one stuck
task cannot block the completion marker indefinitely.

**Total server memory budget**:
```
tier1_instant:    8 workers × ~50MB   =   ~400MB
tier2_fast:       5 workers × ~200MB  =  ~1000MB
tier3_medium:     4 workers × ~400MB  =  ~1600MB
tier4_telemetry:  2 workers × ~900MB  =  ~1800MB
backfill:         2 workers × ~400MB  =   ~800MB
                                         --------
Total Celery:                            ~5600MB
Gunicorn:         4 workers × ~100MB  =   ~400MB
Redis (app):                           ~500MB–1GB
Redis (telemetry):                       ~200MB
PostgreSQL:                              ~500MB
                                         --------
Total server RAM:                       ~8–9GB minimum
```
A 16GB server runs this comfortably with headroom. On an 8GB server: reduce to
4 tier1, 3 tier2, 2 tier3, 2 telemetry, 1 backfill workers.

**Edge cases**
- Parallel writes to the same DB table from multiple workers require non-overlapping row
  scope. Verify each data type writes to separate tables with no overlapping scope.
- The chord callback only fires when all tasks succeed. One stuck task blocks the
  completion marker — set hard timeouts and dead-letter queues per tier.
- Workers in different tiers must be started with explicit `--queues` flags so they
  only consume tasks from their designated queue and never bleed across tiers.

**Priority**: Critical — worker starvation under concurrent load is currently the
hardest ceiling on throughput. No amount of caching helps if telemetry jobs are
blocking standings lookups for 60 seconds.

---

### PROBLEM 4 — Trailing slash 301 redirects

**Root cause**
Every client-side request is missing a trailing slash (e.g. `/api/races/2026/4/results`
instead of `/api/races/2026/4/results/`). Django's `APPEND_SLASH=True` default issues
a 301 redirect on every call, adding a full network round trip before any 200 response.
This affects every single API call without exception.

**Fix — Option A (recommended): Fix the client**
Update all client-side fetch calls to always include the trailing slash. Mechanical
find-and-replace across the frontend codebase. Enforce at the URL construction utility
level, not at individual call sites.

**Fix — Option B: APPEND_SLASH=False**
Makes Django return 404 instead of redirecting. Removes redirect overhead but requires
all `urls.py` patterns to be defined without trailing slashes and changes Django's global
default behavior, risking breakage of admin routes or third-party apps.

**Recommendation**: Option A — fix at the source, zero server-side risk.

**Priority**: High — affects every single API call. Trivial fix.

---

### PROBLEM 5 — No shared session object (in-process session reuse)

**Root cause**
Each endpoint independently creates and loads its own FastF1 session object for the same
race. Two concurrent requests for weather and incidents on the same session both trigger
independent `session.load()` calls, doubling parse work even when FastF1's file-level
cache already has the raw data on disk.

**Fix**
Implement a shared SessionManager that caches loaded session objects in process memory
using a bounded LRU cache. Cap sizes differ by worker type:

- **Gunicorn workers**: cap at 5–7 non-telemetry sessions (weather, incidents, results
  profiles are small with selective loading)
- **Tier3 medium workers**: cap at 4 laps-profile sessions (~20MB each)
- **Tier4 telemetry workers**: cap at 3 full-profile sessions (~100MB each) — this is
  where session reuse has the highest value. Once a session is loaded for VER lap 25,
  LEC lap 25, overlay, compare, and grid summary all come from the same in-memory object
  at serialisation cost only

**Concurrent request handling (request coalescing)**:
When a second request arrives for the same session while the first is still loading,
use a `threading.Event` per session key. The first request acquires the load slot and
sets the event on completion; all others wait on the event, then read from the
now-populated cache. Only one `session.load()` executes per session per worker.

**Edge cases**
- Telemetry session objects are 80–100MB even with selective profiles. Two telemetry
  workers × 3 cached sessions = ~500–600MB dedicated to telemetry session objects.
  Factor this into the tier4 worker memory budget.
- This is a per-worker in-process cache. The Redis write-through cache handles
  cross-worker sharing — the in-process cache eliminates redundant pickle re-parsing
  within one worker for burst traffic on the same session.

**Priority**: High — highest value for telemetry workers where session reuse turns
subsequent driver/lap requests from 15–60s into milliseconds.

---

### PROBLEM 6 — Unified endpoint doesn't minimise load flags

**Root cause**
The `unified/full-session/` endpoint accepts an `include` parameter listing multiple
data types but the session may still be loaded with all flags rather than only those
needed by the requested types.

**Fix**
The unified service derives the minimal flag set from `include` via logical OR before
calling the SessionManager:

- `weather` → `weather=True`
- `incidents` → `messages=True`
- `pit_stops`, `positions`, `drs`, `track_status` → `laps=True`
- Any telemetry type → `laps=True, telemetry=True`

`include=weather,incidents` → `session.load(weather=True, messages=True, laps=False, telemetry=False)`

If the merged profile includes `telemetry=True`, the unified endpoint must route its
Celery task to `tier4_telemetry` rather than the standard tier2 queue.

**Edge cases**
- Verify each data type's actual FastF1 internal dependency before finalising the mapping.
  `positions` depends on lap timing data which requires `laps=True`.
- An invalid `include` type must return HTTP 400 before any session load is attempted.

**Priority**: High — directly compounds the over-loading problem for unified endpoints.

---

### PROBLEM 12 — Blocking I/O in Gunicorn sync workers

**Root cause**
`session.load()` is a blocking network I/O call taking 5–60 seconds. Gunicorn sync
workers are single-threaded — the entire worker is frozen while FastF1 loads. With 4
workers and 4 concurrent cold-miss requests, the entire API becomes unresponsive.
This is the root cause of worst-case response times in the logs.

**Fix — Option A (chosen): Views serve from cache only; Celery owns all FastF1 calls**

Views never call `session.load()` or the SessionManager directly. Every view is
fully non-blocking:

**New request lifecycle**:
1. Request arrives → view checks Redis → hit → return 200 (sub-10ms)
2. Redis miss → view checks PostgreSQL DB → hit → backfill Redis → return 200
3. Both miss → check Redis for existing load lock
   - Lock exists → return 202 with existing task ID and current status
     (`queued` if worker hasn't started yet, `loading` if in progress)
   - No lock → enqueue Celery task to correct tier queue, set Redis lock
     → return 202 with new task ID and status `queued`
4. Client polls `/api/tasks/{task_id}/status/` at 2–5 second intervals
5. Status returns `complete` → client re-fetches original endpoint → hits Redis → 200

**Task status states** (four states, not two):
- `queued` — task is enqueued but no worker has picked it up yet
- `loading` — worker is actively executing the FastF1 load
- `complete` — data is in Redis, client should re-fetch
- `failed` — load failed, client should surface error and offer retry

The distinction between `queued` and `loading` is important for telemetry specifically.
With only 2 tier4 workers, a third concurrent telemetry request may sit in the queue
for 30–60 seconds before a worker is free. Showing "queued behind 2 others" is better
UX than a generic "loading" spinner for 90 seconds with no explanation.

**Task status endpoint**
A lightweight `/api/tasks/{task_id}/status/` endpoint reads Celery task state from
the result backend and returns the four-state status above plus an estimated wait time
derived from queue depth for `queued` tasks. This endpoint must be exempt from all
caching — always return live state.

**Why not the alternatives**:
- **Option B (gevent async workers)**: papers over the symptom. FastF1 still runs inside
  the request lifecycle. gevent monkey-patching introduces known compatibility issues with
  Celery and Django internals. Does not fix the root cause. Rejected.
- **Option C (more workers)**: adds memory and DB connection overhead without solving
  anything structurally. Rejected.

**Expected request distribution in production** (after cache is warm):
- ~95%: Redis hit → 200 in under 10ms
- ~4%: DB hit → 200 in under 100ms
- ~1%: cold miss → 202 → client polls → re-fetch → 200

The 202 case only fires on genuine cold misses. With the bounded cache warm and the
5-year historical DB seed in place, this is rare outside of brand new race weekends.

**Frontend requirement**
The client must handle the 202 pattern:
- Detect 202 and extract the task ID and initial status
- Poll the task status endpoint at 2–5 second intervals
- Show `queued` and `loading` as distinct UI states with appropriate messaging
- Re-fetch the original endpoint when status is `complete`
- Handle `failed` gracefully (show error, offer retry)
- Set a max poll timeout of 3 minutes — surface an error if not complete by then

If the frontend cannot be updated immediately, Option B (gevent) is a valid short-term
bridge. Option A remains the target architecture.

**Edge cases**
- If a Celery task fails, the Redis lock must be explicitly released immediately so
  future requests can retry rather than waiting for TTL expiry
- Task status keys in Redis must have a TTL (10 minutes) so completed task entries
  don't accumulate indefinitely in the result backend
- The task status endpoint must never be cached by any middleware or proxy layer

**Priority**: Critical — root cause of total server stalls under concurrent load.
Implement after Problem 2 (write-through cache) and Problem 3 (tiered queues) are in
place. Non-blocking views only deliver full value when the cache is warm and tasks
are routing to appropriate worker pools.

---

## PART 2 — Cache Architecture

---

### PROBLEM 18 — No bounded cache cycle (unbounded memory growth)

**Root cause**
Loaded session data and DB results have no memory ceiling. A full season of F1 data
across all session types and data type combinations can consume gigabytes of Redis memory
indefinitely. The most frequently accessed data (recent races) has no guarantee of staying
warm while old data silently occupies memory. Telemetry data, if cached in the same Redis
instance as results and standings, will rapidly evict the smaller but more frequently
accessed data due to its size.

**Fix**
Design a two-sided bounded cache cycle split across two Redis databases. All keys carry
TTLs. Both databases use `allkeys-lru` eviction — no permanent keys, no OOM risk,
natural eviction of cold data.

---

**Side 1 — In-process session object cache (per worker process)**

FastF1 session objects cannot be stored in Redis — they are non-serialisable Python
objects. They live in process memory only, managed by the SessionManager.

Per-worker caps by process type:
- Gunicorn workers: 5–7 sessions (non-telemetry profiles, ~5–20MB each)
- Tier3 medium workers: 4 sessions (laps profile, ~20MB each)
- Tier4 telemetry workers: 3 sessions (full profile, ~80–100MB each)

Eviction is application-level using a bounded LRU dict. When the cap is reached, the
least recently accessed session is dropped and released to Python's garbage collector.

Application-level registry: maintain a Redis sorted set `session_lru_registry`
scored by Unix timestamp per worker type. `ZADD` on every load, `ZRANGE` + `ZREM`
when cap is exceeded. This gives exact count-based eviction independent of memory pressure.

**Memory budget for in-process caches**:
```
Gunicorn (4 workers × 6 sessions × ~15MB avg):      ~360MB
Tier3 workers (4 workers × 4 sessions × ~20MB):      ~320MB
Tier4 workers (2 workers × 3 sessions × ~90MB):      ~540MB
Total in-process session cache:                      ~1220MB
```

---

**Side 2a — Main app Redis cache (non-telemetry)**

All serialised JSON from DB queries and FastF1 loads for results, weather, incidents,
standings, positions, laps, stints, and all other non-telemetry data.

**Redis configuration**:
- `maxmemory`: 500MB–1GB (half of available RAM not allocated to workers)
- `maxmemory-policy`: `allkeys-lru`
- `maxmemory-samples`: 10

**TTL ladder**:

| Data type | TTL | Rationale |
|-----------|-----|-----------|
| Historical completed season (>1 year ago) | 7 days | Final, rarely accessed |
| Current season completed race | 6–12 hours | Final, frequently accessed |
| Current season in-progress race | 60–120 seconds | Updates during live session |
| Weather / track status | 5 minutes | Changes mid-session |
| Qualifying results | 4 hours | Final after session ends |
| Driver / constructor standings | 1 hour | Updates after each race only |
| In-flight lock keys (non-telemetry) | 90–120 seconds | Exceeds max non-telemetry load time |
| Task status keys | 10 minutes | Polling window only |

---

**Side 2b — Telemetry Redis cache (separate database)**

Telemetry data lives in a dedicated Redis database with its own memory ceiling,
separate from the main app cache. This prevents large telemetry payloads (100KB–500KB
per driver per lap) from evicting small but high-traffic data like standings and results.

**Redis configuration**:
- `maxmemory`: 200MB (telemetry is accessed in bursts then goes cold quickly)
- `maxmemory-policy`: `allkeys-lru`
- `maxmemory-samples`: 10

**TTL ladder**:

| Data type | TTL | Rationale |
|-----------|-----|-----------|
| Single driver lap trace | 30 minutes | Burst-accessed then cold |
| Overlay (two drivers) | 30 minutes | Same burst pattern |
| Compare (N drivers) | 1 hour | More expensive to regenerate |
| Grid summary (all drivers) | 2 hours | Most expensive, worth keeping longer |
| In-flight lock keys (telemetry) | 180 seconds | Exceeds max telemetry load time |

Short TTLs are appropriate because the in-process session cache (Problem 5, tier4
workers) means regeneration is cheap once the session is in memory — serialisation cost
only, not a full FastF1 reload.

---

**Three Redis instances (not one)**

```
Redis 1 — App cache (allkeys-lru, 500MB–1GB ceiling)
  → All non-telemetry serialised results
  → Session LRU registry sorted sets
  → Non-telemetry in-flight lock keys
  → Task status keys

Redis 2 — Telemetry cache (allkeys-lru, 200MB ceiling)
  → All telemetry serialised traces
  → Telemetry in-flight lock keys

Redis 3 — Celery broker + result backend (noeviction)
  → Task queue messages
  → Task result storage
  → Sized for task queue depth, not data storage
```

A broker restart during deployment must not affect the app or telemetry cache. A
telemetry cache eviction must not affect results or standings. Complete isolation between
all three databases. Use separate Redis instances rather than separate `db` indices for
true process-level isolation — a single Redis process failure should not take down all three.

---

**How the cache cycle works in practice**:
1. New race weekend → cold misses → 202 → Celery loads → writes to Redis 1 or 2 by type
2. During race weekend → all requests hit Redis 1/2 → sub-10ms responses
3. After race weekend → TTLs tick down; LRU keeps most-accessed data warm naturally
4. Mid-season → last 2–3 race weekends stay hot; earlier data evicts under pressure
5. Telemetry bursts (user analysing a race) → Redis 2 fills with that session's traces
   → when user stops, TTLs expire and traces evict leaving Redis 2 ready for next burst

**Edge cases**
- Never assume a key is present even immediately after writing it — always handle cache
  misses gracefully throughout the read chain
- Monitor `evicted_keys` and keyspace hit/miss ratios on all three Redis instances
  independently. A rising eviction rate on Redis 1 signals the ceiling is too tight.
  A high miss rate on Redis 2 signals telemetry is not benefiting from caching.
- The sorted set session registry clears on Redis restart, but this is acceptable —
  in-process session objects are gone too on a restart. Recovery is natural.

**Priority**: High — prevents memory bloat across a full season and keeps hot data warm
without manual intervention.

---

### PROBLEM 19 — No dedicated telemetry cache system

**Root cause**
Telemetry is a fundamentally different workload class from every other endpoint. It
requires the heaviest load profile (`laps=True, telemetry=True`), produces the largest
serialised responses (100KB–500KB per driver per lap), is accessed in tight user-driven
bursts (VER lap 25 → LEC lap 25 → overlay → compare in quick succession), and then
goes completely cold. Treating it the same as a standings lookup causes memory pressure,
worker starvation, and unpredictable eviction of high-traffic non-telemetry data.

**Fix**
Design a dedicated telemetry subsystem covering cache, workers, and request flow as
a coherent unit separate from the rest of the API.

**Telemetry-specific cache (Redis 2)**
Described fully in Problem 18 Side 2b. Key points:
- 200MB dedicated ceiling, separate Redis instance from the main app cache
- `allkeys-lru` eviction — telemetry traces evict independently of results/standings
- Short TTLs (30 minutes for single traces) because in-process session reuse makes
  regeneration cheap once the session object is in the tier4 worker's memory

**Telemetry-specific in-process session cache (tier4 workers)**
Each tier4 telemetry worker maintains its own in-process session object cache
capped at 3 sessions. This is where the highest session reuse value lives:
- User requests VER lap 25 → cold load, session object cached in tier4 worker memory
- User requests LEC lap 25 → session object already in memory → serialisation only
- User requests overlay VER vs LEC → session object already in memory → milliseconds
- User requests grid summary → session object already in memory → milliseconds
- Only the first request for a session costs the full 15–60 second FastF1 load

With 2 tier4 workers capping at 3 sessions each, up to 6 different race sessions
can be held in telemetry worker memory simultaneously covering burst analysis windows.

**Telemetry request queue and status**
With only 2 tier4 workers, queue depth matters. The task status endpoint must return
`queued` (with estimated position) vs `loading` (with elapsed time) as distinct states.

Estimated wait time for `queued` telemetry tasks:
- Check the tier4 queue depth from the Celery result backend
- Multiply queue position by average telemetry task duration (~20s for cached session,
  ~60s for cold load) to give the client a realistic ETA
- Update this estimate on each status poll

**What to cache in Redis 2 vs what to leave in-process only**

Cache in Redis 2 (shared across all workers and requests):
- Single driver lap traces with `stride` applied (downsampled for charting)
- Overlay traces for common driver pair + lap combinations
- Grid summary (all drivers, fastest lap, aggregated only — not raw points)

Do NOT cache in Redis 2 (too large, too rarely re-requested identically):
- Full-resolution telemetry (2000+ points per lap) — only cache downsampled versions
- Raw telemetry arrays before stride/limit_points filtering — apply filters first,
  cache the filtered result

The cache key must include the `stride` and `limit_points` parameters because two
requests for the same lap with different stride values are different data. Key format:
`telemetry:{year}:{round}:{session}:{driver}:{lap}:{stride}:{limit_points}`

**Selective prefetch within a session**
When a telemetry request warms a session in a tier4 worker, the worker should
proactively serialise and cache the fastest lap traces for all 22 drivers from that
session to Redis 2 at low priority in the background. This means:
- User requests VER lap 25 → session loads → VER trace returned immediately
- In background → all 22 fastest lap traces serialised to Redis 2 with 30min TTL
- User requests LEC fastest lap → Redis 2 hit → instant response
- User requests grid summary → all traces already in Redis 2 → instant assembly

This background serialisation task runs at lower priority than the original request
and should not block the response. It is not a Celery task — it is work the tier4
worker does after returning the primary response, using the already-loaded session.

**Edge cases**
- The background fastest-lap prefetch must respect the Redis 2 `maxmemory` ceiling.
  If Redis 2 is near capacity, skip the background prefetch rather than forcing eviction
  of other recent telemetry data.
- Full-resolution telemetry for 22 drivers would be ~10MB+ per session uncompressed.
  Always apply a default `stride=5` or `limit_points=500` before caching in Redis 2.
  The API must document that cached telemetry is pre-downsampled.
- A user requesting stride=1 (full resolution) will always miss the pre-downsampled
  cache and trigger a fresh serialisation from the in-process session object.

**Priority**: High — without dedicated telemetry isolation, a single grid-wide telemetry
request can evict an entire race weekend's worth of results and standings data from
the shared Redis cache, degrading performance for all other users simultaneously.

---

## PART 3 — Historical Data & Predictive Prefetching

---

### PROBLEM 20 — Cold loads for frequently-requested historical data

**Root cause**
Historical race data for the last 5 seasons (2020–2024) is completely static — it will
never change — yet every first request triggers a cold FastF1 load because the DB has
not been seeded. Users performing comparison queries (Hamilton vs Verstappen 2021,
constructor standings history) consistently hit 20–60 second cold loads for data that
could have been in the DB permanently.

**Fix: 5-year historical DB seeding**

A Django management command running once uses the `backfill` Celery queue to seed all
historical data into PostgreSQL at low priority.

**What to seed** (small, always-requested, completely static):
- Race results (all rounds, all years)
- Qualifying results
- Driver and constructor standings per year
- Driver career aggregates
- Incidents and race control messages
- Weather per session
- Stint and pit stop data
- Positions / lap summaries

**What NOT to seed** (too large, rarely needed for historical browsing):
- Raw telemetry point-by-point data — leave on-demand via 202 pattern

**Seeding order**: 2024 → 2023 → 2022 → 2021 → 2020. Most recent year first so that
if the process is interrupted, the most-requested historical data is already available.

**GitHub schedule dependency**
FastF1 fetches the F1 season schedule from `raw.githubusercontent.com` on every session
instantiation. When this times out (as shown in logs), it adds 10–15 seconds of dead
time to every cold load — potentially 240+ timeouts across a 5-year seed run. Pre-populate
FastF1's local schedule cache from your DB schedule data before dispatching any seeding
tasks. This eliminates the GitHub dependency entirely for all completed seasons.

**Rate limiting**: use the `backfill` queue's 3-tasks-per-minute rate limit to avoid
hammering the FastF1 API. The seed runs overnight or over a weekend, not in a single burst.

**After seeding**:
- 5 years of historical data is always served from DB (milliseconds)
- Redis write-through backfills the hot data on first user access after seeding
- FastF1 is only called for: current season recent rounds, on-demand telemetry,
  and any gap in the historical seed

**Priority**: High — eliminates cold loads for the most comparison-heavy data in the system.

---

### PROBLEM 21 — No predictive prefetching for race weekends

**Root cause**
After a race completes, the first user to request any data for that round triggers a
cold FastF1 load. Traffic spikes immediately after a race ends — exactly when the data
is coldest. There is no mechanism to proactively warm the cache between race completion
and the traffic spike.

**Fix: Race weekend completion trigger**

When a race session is detected as complete (via schedule-aware detection or the first
results fetch), fire a Celery `group()` via the `backfill` queue that proactively loads
and caches the four highest-traffic endpoints for that round:

1. Race results (tier2, ~8KB serialised)
2. Qualifying results (tier2, ~3KB serialised)
3. Incidents (tier2, ~20–40KB serialised)
4. Weather (tier2, ~25KB serialised)

**Memory budget for proactive prefetch**:
```
4 endpoints × ~80KB average × 3 recent rounds = ~1MB
```
Against a 500MB Redis 1 ceiling, this is negligible. The LRU policy handles the rest —
data that nobody requests after being prefetched will evict naturally.

**What NOT to prefetch**: telemetry, raw laps, positions, stints. These are on-demand
only. Prefetching them would waste both Redis memory and Celery worker time on data
that may never be requested before eviction.

**Adjacent round prefetch**
When round N is accessed, also check whether round N-1 is in Redis. If not, and round
N-1 is a completed race, enqueue a low-priority prefetch for its four core endpoints.
Users browsing a race weekend frequently navigate to the previous race for comparison.

**Edge cases**
- The prefetch group must run on the `backfill` queue, not tier2, so it doesn't compete
  with live user requests during the post-race traffic spike
- Detect race completion via schedule data (session end time has passed) or by checking
  whether race results are available from FastF1 — do not rely on a webhook or external
  trigger that may not fire reliably
- Do not prefetch future rounds — the data doesn't exist yet

**Priority**: Medium — the cache and seeding (Problems 2, 18, 20) are more impactful.
Prefetching is the final layer that eliminates the last cold-miss window.

---

## PART 4 — General Django API Performance Mistakes

---

### PROBLEM 7 — N+1 query problem in ORM calls

**Root cause**
When endpoints retrieve race results, driver standings, or session data from PostgreSQL,
DRF serializers or view logic may trigger one database query per object in a loop instead
of a single joined query. A results endpoint returning 22 drivers could execute 22+
queries when it should execute 1–2.

**Fix**
Audit every endpoint serializing a queryset with related model data:

- `select_related()` for ForeignKey and OneToOne relationships (driver → team,
  result → race) — converts N+1 into a single SQL JOIN
- `prefetch_related()` for reverse ForeignKey and ManyToMany (race → all results,
  driver → all season entries) — two queries total, joined in Python

In DRF, nested serializers are the most common hidden N+1 source. Every nested serializer
must have its related queryset pre-fetched at the view level before serialization begins.
The serializer never issues its own queries.

**Detection**: Enable Django query logging in development. Any list endpoint executing
more than ~3 queries has an N+1 problem. Use `django-querycount` middleware to surface
this automatically during development.

**Edge cases**
- Combine `select_related()` with `.only()` to avoid fetching unused columns from joins
- `prefetch_related()` joins in Python — can use significant memory for large sets.
  Scope with `Prefetch()` and a filtered queryset.
- DRF's `depth` parameter auto-generates nested serializers without prefetching and is
  almost always an N+1 source. Avoid it entirely.

**Priority**: Critical for any endpoint touching related models.

---

### PROBLEM 8 — Over-fetching in querysets (.only / .values)

**Root cause**
`Model.objects.filter(...)` fetches all columns from the table. Race result rows likely
have 15–25 fields; if the response only uses 8, the remaining 17 are fetched, deserialised,
and discarded on every request.

**Fix**
Apply `.only('field1', 'field2', ...)` to fetch only columns needed for the response.
For read-only endpoints that never need full model instances, `.values('field1', 'field2')`
returns plain dicts directly from the DB with no model instantiation overhead.

The serializer's `fields = [...]` declaration controls what is serialised but does NOT
control what the ORM fetches. Both must be scoped independently to the same minimal set.

**Edge cases**
- `.only()` defers omitted fields lazily — if any code path accesses a deferred field,
  Django issues an extra query per object, worse than not using `.only()` at all.
- `.values()` returns dicts, not model instances — model methods on serializers break.

**Priority**: High for high-traffic list endpoints.

---

### PROBLEM 9 — Missing database indexes on filter columns

**Root cause**
Endpoints filter by `year`, `round`, `driver_code`, and `session_type` on every request.
Without indexes, PostgreSQL performs a full table scan. As results grow (22 drivers ×
24 rounds × multiple seasons), scan times grow linearly.

**Fix**
Add single-column indexes on: `year`, `round`, `driver_code`, `session_type`.
Add composite indexes for common combinations: `(year, round)`,
`(year, round, session_type)`, `(year, driver_code)`.

Confirm with `EXPLAIN ANALYZE` — queries should show `Index Scan` not `Seq Scan`.

**Edge cases**
- Indexes speed reads but slow writes. Since race data is written once and read many
  times, this tradeoff strongly favours indexing.
- Schedule PostgreSQL `VACUUM` and `ANALYZE` to prevent index bloat over time.

**Priority**: High — zero application code change, pure database configuration.

---

### PROBLEM 10 — Database connection overhead (CONN_MAX_AGE)

**Root cause**
Django's default `CONN_MAX_AGE=0` closes the DB connection after every request.
Establishing a new PostgreSQL connection costs 5–50ms per request. Under concurrent
load with multiple Gunicorn workers and Celery workers this compounds significantly.

**Fix — Step 1: Persistent connections**
Set `CONN_MAX_AGE=60` in `DATABASES` settings. Each worker reuses its connection across
requests within that window. Total connections = all workers across all pools + Gunicorn.
Ensure this does not exceed PostgreSQL's `max_connections` (default 100).

**Fix — Step 2: PgBouncer**
Deploy PgBouncer as a connection pooling proxy for production. In transaction pooling
mode, a PostgreSQL connection is only held during an active transaction. Set
`CONN_MAX_AGE=0` when using PgBouncer — let it manage connection lifecycle.

**Edge cases**
- Include all Celery worker pools in the total connection budget — 21 workers across
  five queues all open DB connections independently.
- Use `CONN_HEALTH_CHECKS=True` (Django 4.1+) to validate connections before reuse.
- PgBouncer transaction mode is incompatible with advisory locks and `SET` statements
  spanning multiple transactions.

**Priority**: High — low-effort config change with measurable latency reduction.

---

### PROBLEM 11 — DRF serializer over-inclusion and nested N+1

**Root cause**
Serializers declaring `fields = '__all__'` or nesting related serializers without
prefetching are a hidden performance cost at the Python layer. Each nested serializer
level may trigger an additional DB query per parent row.

**Fix**
Implement tiered serializers per endpoint use case:

- **List serializers**: minimal fields, no nesting — collection endpoints
- **Detail serializers**: full fields with nesting — single-object endpoints

All nested serializer data must be prefetched at the view level before serialization
begins. The serializer never issues its own queries.

**Priority**: High for list endpoints with related data.

---

### PROBLEM 13 — Unpaginated large responses

**Root cause**
Laps, telemetry, positions, and incidents endpoints can return thousands of rows per
response. The existing `limit=` parameter is a manual cap, not true pagination.

**Fix**
Implement DRF cursor-based pagination on all multi-row endpoints:
- Scales without `OFFSET` degradation
- Stable — inserting rows doesn't shift page boundaries
- Natural cursors: `lap_number` for lap data, `session_time` for timing data

Default page sizes: telemetry 500 points (with existing `stride`), laps 25, positions 50.
Weather needs no pagination (under 100 samples per session).

**Edge cases**
- Use composite cursors (`lap_number, driver_code`) to prevent cross-page duplicates.
- Document the migration from `limit=` clearly to avoid breaking existing clients.

**Priority**: Medium for most endpoints. High for telemetry.

---

### PROBLEM 14 — Unnecessary middleware on all routes

**Root cause**
Session, CSRF, and authentication middleware run on every request including public
read-only API endpoints that need none of them.

**Fix**
- Remove CSRF middleware for read-only or token-authenticated endpoints
- Remove session middleware for stateless REST APIs
- Cache auth DB checks in Redis with a short TTL (60s)

**Edge cases**
- Django admin requires session middleware and CSRF — split by URL prefix before removing.

**Priority**: Medium — small gain per request but affects every call.

---

### PROBLEM 15 — DEBUG=True in production

**Root cause**
`DEBUG=True` causes Django to collect full SQL query logs and stack traces in memory on
every request. Significant overhead with zero production benefit.

**Fix**
`DEBUG=False` in production via environment variable. Configure Sentry or Datadog for
error capture.

**Edge cases**
- `DEBUG=False` stops Django serving static files — ensure Nginx serves them.
- `ALLOWED_HOSTS` must be explicitly set or Django rejects all requests with 400.

**Priority**: High if not already done — misconfiguration, not optimisation.

---

### PROBLEM 16 — Response compression not enabled

**Root cause**
Large JSON responses (telemetry, positions, weather) are sent uncompressed. A 25–40KB
response could be 5–10× smaller with GZIP.

**Fix**
Enable GZIP at the Nginx layer with a 1KB minimum threshold. `GZipMiddleware` only as
fallback for development connections.

**Edge cases**
- Limit to `application/json` and `text/*` — not binary formats.
- GZIP is incompatible with streaming responses.

**Priority**: Medium — zero Django code change, pure Nginx configuration.

---

## PART 5 — Observability

---

### PROBLEM 17 — No request-level profiling

**Root cause**
Without per-request timing data broken down by layer (Redis, DB, FastF1, serialisation,
queue depth), there is no way to verify optimisations are working or identify the next
bottleneck. With five worker pools and three Redis instances, the observability surface
is significantly larger than a standard Django app.

**Fix**
Instrument every layer with structured log lines and build a unified dashboard:

**Per-request instrumentation**:
- **Redis 1 (app cache)**: log every hit/miss with key, TTL remaining, and latency
- **Redis 2 (telemetry cache)**: log separately — hit/miss ratio, eviction rate
- **DB query time**: `django-silk` in development, Datadog APM in production
- **FastF1 SessionManager**: `(year, round, session_type, load_profile, duration_ms,
  cache_hit, worker_pool)` on every load — extend the existing logging pattern
- **202 cold miss flow**: log time from 202 issued → `queued` → `loading` → `complete`
  → client re-fetch. This end-to-end latency is the key metric for cache warmth.
- **Task status transitions**: log every state change per task ID with timestamp
- **End-to-end response time**: extend the existing `duration_ms` logging to all
  endpoint types, not just unified endpoints

**Per-queue instrumentation**:
- Queue depth per tier (tier1 through tier4 + backfill)
- Active worker count per tier
- Task duration p50/p95/p99 per task type
- Worker memory usage per pool (alert if approaching tier budget)
- Tier4 telemetry queue: log queue position for `queued` tasks so the estimated wait
  time returned to clients is based on real data, not a fixed estimate

**Dashboard** (Grafana + Prometheus or Datadog):
- p50 / p95 / p99 response time per endpoint, split by cache layer (Redis / DB / 202)
- Redis 1 hit rate per data type (target >90% for completed race data)
- Redis 2 telemetry hit rate (lower acceptable — telemetry is burst-accessed)
- 202 cold miss rate over time (should trend toward zero as cache and seeding warm)
- Celery queue depth and worker utilisation per pool separately
- DB query count per request (N+1 regression detection)
- `evicted_keys` from all three Redis instances (signals ceiling too tight)
- Backfill queue progress (rounds seeded vs total, ETA to completion)

**Edge cases**
- With 21 Celery workers across 5 queues plus 4 Gunicorn workers, structured log
  correlation requires a consistent `request_id` or `task_id` threaded through every
  log line. Without this, tracing a single request across worker logs is impossible.
- Instrumentation adds overhead. Keep it as structured log lines — the FastF1 load
  logging already in the codebase is the right pattern. Extend it consistently.

**Priority**: High — instrument before making other changes to establish a baseline.
Without per-queue visibility you cannot tell whether worker starvation is still
occurring after the tiered queue architecture is in place.

---

## Implementation Phases

| Phase | Problem | Impact | Effort | Notes |
|-------|---------|--------|--------|-------|
| Baseline | #17 Observability | High | Medium | Instrument first — baseline before optimising |
| 1 — Quick wins | #4 Trailing slash | High | Trivial | Fix all client call sites |
| 1 — Quick wins | #15 DEBUG check | High | Trivial | Environment variable |
| 1 — Quick wins | #10 CONN_MAX_AGE | High | Low | One settings change + PgBouncer plan |
| 1 — Quick wins | #9 DB indexes | High | Low | Pure DB config, EXPLAIN ANALYZE to verify |
| 2 — FastF1 | #1 Selective loading | Critical | Low | Biggest single latency win |
| 2 — FastF1 | #6 Unified flag merge | High | Low | Pair with #1 |
| 3 — Queue arch | #3 Tiered queues + workers | Critical | High | Foundation for #12 and #19 |
| 3 — Queue arch | #19 Telemetry subsystem | High | High | Pair with #3 |
| 4 — Cache layer | #2 Write-through Redis | Critical | Medium | Requires #3 queue routing in place |
| 4 — Cache layer | #18 Bounded LRU + 3 Redis | High | Medium | Pair with #2 |
| 4 — Cache layer | #5 In-process session reuse | High | Medium | Pair with #2, different caps per pool |
| 5 — Non-blocking | #12 Option A views + 4-state status | Critical | High | Requires Phase 4 complete |
| 6 — Data seeding | #20 5-year historical seed | High | Medium | Backfill queue + GitHub schedule fix |
| 6 — Data seeding | #21 Race weekend prefetch | Medium | Medium | Pair with #20 |
| 7 — DB / ORM | #7 N+1 audit | Critical | Medium | Ongoing per endpoint |
| 7 — DB / ORM | #8 .only() / .values() | High | Medium | Ongoing per endpoint |
| 7 — DB / ORM | #11 Serializer tiers | High | Medium | Ongoing per endpoint |
| 8 — Polish | #13 Cursor pagination | Medium | Medium | After core fixes |
| 8 — Polish | #14 Middleware audit | Medium | Low | When stable |
| 8 — Polish | #16 GZIP compression | Medium | Low | Nginx config |

**Phase rationale**:
- **Baseline first**: you cannot measure improvement without a baseline. The 202
  cold miss rate and per-queue depth metrics are especially important — they are
  the primary signal that the architecture is working.
- **Phase 1 (quick wins)**: near-zero risk, immediate effect on every request.
- **Phase 2 (selective loading)**: fixes the 28–67s response times directly. Highest
  latency reduction per unit of effort across the entire project.
- **Phase 3 (queue architecture)**: must come before the cache layer because tasks
  need to route to the correct queue before the write-through pattern is valuable.
  A telemetry task on the main cache Redis is still a problem even with write-through.
- **Phase 4 (cache layer)**: builds on top of correct queue routing. The three-Redis
  separation, bounded LRU caps, and TTL ladders all depend on tasks knowing which
  queue and cache database they belong to.
- **Phase 5 (non-blocking views)**: the 202 pattern only delivers its full value when
  cache hit rates are high and tasks route to appropriate pools. A 202 that resolves
  in 3s (warm cache, correct pool) is acceptable UX. A 202 that takes 90s because
  telemetry and standings share a queue is not.
- **Phase 6 (seeding)**: once the architecture is stable, seed historical data to
  permanently eliminate cold loads for 5 years of race history.
- **Phases 7–8**: ongoing improvements that compound on top of the core architecture.

---

*Last updated: May 2026 | Stack: Django + FastF1 3.8.x + Celery + Redis + PostgreSQL*
