# A1 trackmap progress

## Phase 1a: TrackGeometry model, geometry builder, build task

Status: done, awaiting review.

Files (all under `backend/api/trackmap/`): `models.py`, `migrations/0001_initial.py`, `geometry.py`, `tasks.py`, `tests/test_geometry.py`, `NEEDS.md`.

Tests: full suite 216 passed, 2 failed (the known `test_driver_endpoints` readiness pair), 16 skipped. Baseline 210/2/16, so +6 passed, no new failures. Migration applies on SQLite in tests (trackmap migrations are not disabled in `settings_test`).

Design choices
- Downsample by fixed distance step (1,500 points), not Douglas-Peucker: a uniform grid keeps index <-> distance linear, which mini-sectors and the Phase 1c delta interpolation rely on. About 3.5 m per step on a 5.3 km lap.
- x/y/z kept in FastF1 units (1/10 m); distance in metres.
- Mini-sectors stored as boundary lists for both schemes: `{"distance": {boundaries}, "corners": {boundaries, labels}}`. Corner scheme = one sector per corner, cut at midpoints between neighbouring corner distances.
- DRS zone = contiguous run of DRS channel >= 10 (FastF1 docs: 0-14, even enabled; 8 is eligible only), at least 50 m long. Empty list when there is no DRS channel (2026 regs).
- `layout_hash` = sha256 of a coarse signature (lap length to 25 m, 48 points at fixed lap fractions rounded to 20 m). Coarse so racing-line noise between years does not mint a new layout. Known limit: values on a rounding edge can flip it (costs one extra row).
- `circuit_key` = `session_info["Meeting"]["Circuit"]["Key"]` (same key FastF1 uses for `get_circuit_info`). `year` = first year the layout was built.
- Task `api.trackmap.tasks.build_track_geometry(year, round)`: loads Q (falls back to R) through `SessionManager.get_session(..., required_types=["telemetry"])`; `get_or_create` on (circuit_key, layout_hash); writes the payload permanently (`timeout=None`) to `telemetry_cache` under `trackmap:geometry:{circuit_key}:{layout_hash}`, plus a pointer `trackmap:built:{year}:{round}` so a repeat call returns before touching FastF1.

DEFERRED-VM: none. Real-session check against live FastF1 data not done (no network in this phase); builder verified on synthetic telemetry only.

Open questions
- A real lap's `get_telemetry()` may not end exactly at the start point; the loop-closure test is on a synthetic closed lap. Worth one live check at first VM run.
- Sprint-only or cancelled-Q weekends fall back to the race session; the race "fastest lap" is not a pole lap but is fine for outline.

Needs from orchestrator
- Ingestion hook (outside my files): after a Q (or R) session finishes populating, call `from api.trackmap.tasks import build_track_geometry; build_track_geometry.delay(year, round_number)`. The task is idempotent, so calling it on every ingestion is safe. Likely spot: end of the telemetry/session populate task in `api/tasks.py` or `api/workers`.
- Add `pytest` and `pytest-django` to a requirements file or the venv bootstrap docs: `requirements.txt` has neither, so a fresh venv cannot run the suite (I installed pytest 9.0.3 and pytest-django 4.12.0 matching the original venv). `pytest.ini` also sets `asyncio_mode`, which warns as unknown without pytest-asyncio (same as baseline).

## Phase 1b: endpoints (track-map, mini-sectors, telemetry/delta)

Status: done, awaiting review. Rebased on v2/integration (f57504f) first.

Files (all in `backend/api/trackmap/`): `service.py` (geometry lookup, param parsing, lap traces, response builders), `views.py`, `serializers.py` (schema shapes), `urls.py`, `tasks.py` (key helpers moved to `service.py`, re-exported; new `populate_track_geometry`), `tests/test_endpoints.py`.

Tests: full suite 246 passed, 2 failed (known pair), 16 skipped. Baseline 216/2/16, so +30, no new failures. drf-spectacular generation emits no warnings for the new views.

Design choices
- Auth, permission and throttle are the project defaults (APIKeyAuthentication, IsAPIKeyAuthenticated, APIKeyThrottle), not redeclared, so they match every analysis view by construction; a test asserts the class lists equal `AnalysisTelemetryAPIView`'s, and that no-key requests get the same status as `/laps/`. Cost: `track-map` uses endpoint_type `track_map` (not in `ENDPOINT_COSTS`, so cost 1); `mini-sectors` and `delta` use `telemetry` (cost 5).
- `track-map`: `handle_data_request`. Geometry read = cache pointer, cached payload, DB row (re-warms the cache). Miss enqueues `populate_track_geometry` (task_key first, like the other populate_* tasks, task key `track_map:{y}:{r}:{scheme}`) and streams the track-map response when done.
- `mini-sectors` and `delta`: on a geometry miss they enqueue the same build and return 202 `{status: pending, task_key, detail}` (streaming would publish the track-map shape, not theirs). Missing telemetry for a driver or lap returns 404 with the driver named. Say if you would rather have these stream too.
- Telemetry source: persisted `DriverTelemetry` (what `populate_telemetry` writes). Those laps hold `distance` and `speed` but NO time channel (`extract_telemetry` looks for `time`, the writer never stores it). So time = integral of dd / v. When the lap table (`DriverLapAnalysis`, race sessions only) has the lap time, the trace is scaled so segments sum to it (`lap_time_source: official`); otherwise `integrated`. Each lap's distance is rescaled to the geometry length so boundaries line up and the sector times sum to the lap time exactly (the test checks within 0.03 s).
- `lap=fastest`: fastest timed lap per driver among complete laps (>= 90 % of the longest distance), so in/out laps cannot win; lap time from the lap table if present, else integrated time. `lap=<n>` applies to every driver.
- Delta: positive = cmp slower than ref, on the geometry's 1,500-point distance grid, columnar. Delta at the last point equals the lap-time difference.
- Params: `drivers` (1-20 unique 3-letter codes), `ref`/`cmp` 3-letter, `lap` fastest or int >= 1, `scheme` distance|corners, `session` R default plus Q,S,SQ,FP1-3; all 400 on bad input.

Open questions
- Integrated time from speed samples is an approximation (sampling and speed noise), good to a few tenths over a lap before official scaling; per-sector error after scaling is shared across the lap rather than corrected per sector. A time channel in the persisted payload would remove this (touches populate_telemetry, which I do not own).
- Persisted telemetry is car data only; no per-lap X/Y, so nothing projects onto the geometry by position, only by distance.
- `TASK_TIER_MAP` in `api/queue/manager.py` has no entry for `populate_track_geometry`, so the lock TTL defaults to 90 s (tier3 default) and the `queue="tier4_telemetry"` on the task itself still decides routing. Suggest adding `"populate_track_geometry": ("tier4_telemetry", 180)`.

DEFERRED-VM: none. Not exercised against real persisted telemetry.

Needs from orchestrator
- (carried over) ingestion hook calling `build_track_geometry.delay(year, round_number)`; pytest and pytest-django in requirements.
- Optional `TASK_TIER_MAP` entry above; optional `ENDPOINT_COSTS["track_map"]` if cost 1 is not wanted.
