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

## Phase 1c: optional telemetry params, stored time channel

Status: done, awaiting review. Rebased on v2/integration (d1746a9) first.

Commits: golden snapshots first (captured from the unmodified views, before any edit), then the implementation.

Files
- New in `backend/api/trackmap/`: `telemetry_params.py` (parsing, slicing, channel selection, columnar, cache-key suffix, a content-negotiation class), `tests/telemetry_fixture.py`, `tests/test_telemetry_defaults.py`, `tests/test_telemetry_params.py`, `tests/golden/*.json` (8 snapshots).
- Edited: `api/session/views.py` (telemetry and overlay views), `api/services/analysis.py` (`fetch_telemetry_snapshot`, `fetch_telemetry_overlay`), `api/trackmap/service.py` (time channel in mini-sectors and delta), `api/management/commands/populate_telemetry.py` (writes the time channel; this is where `DriverTelemetry` payloads are built, outside the files named in the brief, so flagging it). `api/tasks.py` and `unified_service.py` needed no change: `api/tasks.py` only re-exports the worker, and the persisted payload is written by the command that `populate_session_telemetry` calls.

Tests: full suite 289 passed, 2 failed (known pair), 16 skipped. Baseline 246/2/16, so +43, no new failures.

What was added
- `start_m`, `end_m` (metres, inclusive, `start_m < end_m`), `channels` (subset of speed, throttle, brake, gear, rpm, drs, time), `format=rows|columnar` on `telemetry/` and `telemetry/overlay/`. Any bad value returns 400.
- Defaults: with none of the four given the original code path runs unchanged. 8 golden snapshots (single lap, all laps, `limit_points`, `stride`, sector window, whole session, overlay, overlay limited) compare raw response bytes; a second run repeats them on rows that DO carry the new time array, proving it never leaks.
- Rows with `channels`: `driver_code`, `lap_number`, `distance_m` plus the chosen channels (`speed_kph`, `throttle_pct`, `brake`, `gear`, `rpm`, `drs` as a boolean flap-open flag, `time_seconds`). `filters_applied` gains `start_m`, `end_m`, `channels`, `format` only when a new param is used. Columnar is `data: {key: [values]}` (overlay: per trace), every key a list, equal to the rows value for value (tested, including with slicing, stride and all channels).
- Cache keys get a suffix only when a new param is present, so default cache entries are untouched and columnar never collides with rows.
- Time channel: `populate_telemetry` now stores `elapsed_s` (seconds from the lap's first sample, from the FastF1 `Time` column; omitted if the frame has no Time) in each lap. `extract_telemetry` ignores it, so defaults are unchanged. `channels=...time` returns it as `time_seconds` (null on rows stored before this change).
- Mini-sectors and delta use stored time when present. `lap_time_source`: `telemetry` (stored time; wins even if the lap table has a time), `official` (lap table, scaling the integrated curve), `integrated` (speed integration). Old rows keep working through the fallback; a mixed request reports the source per driver.

Gotcha found: DRF treats `?format=<x>` as a renderer choice and returns 404 for anything but json. The two views now use a content-negotiation class that turns that override off (JSON is their only renderer), so `format=columnar` reaches the view.

Payload and latency (fixture: one lap of 400 samples, 9 channels as stored, Django test client, median of 30 requests, local, SQLite, includes auth and throttle overhead)

| Request | Raw bytes | Gzip bytes | Server ms |
|---|---|---|---|
| 1 lap, rows (default) | 65,650 | 6,533 | 11.2 |
| 1 lap, columnar | 20,246 | 4,954 | 4.3 |
| 1 lap, rows, channels=speed,throttle,brake | 44,934 | 4,963 | 7.7 |
| 1 lap, columnar, channels=speed,throttle,brake | 14,225 | 3,728 | 4.2 |
| 1 lap, columnar, start_m=1000 end_m=2000 | 4,204 | 1,353 | 3.2 |
| 2 laps, rows (default) | 130,966 | 12,516 | 22.0 |
| 2 laps, columnar | 39,962 | 7,315 | 6.3 |

Columnar is 69 % smaller raw and 24 % smaller gzipped for a full lap (7,315 vs 12,516 for two laps: 42 %). Part of the time gain is that the non-default path skips the row serializer. Caveat: rows here include `driver_code`, `lap_number`, `sector` as repeated per-sample fields; real laps will be similar.

Open questions
- `telemetry/summary/` was left out: its DB path is already broken on master (`get_telemetry_summary` is never imported in `session/views.py`, so it always falls through to the task, whose serializer then fails on a missing `limit_max`). Fixing it changes current behaviour, so I did not. Say if you want it fixed as a separate change.
- On a DB miss the endpoints still enqueue the existing task, whose live FastF1 path ignores the new params; the streamed result is the default row shape. A retry after the task has stored the data honours them. The live FastF1 extraction (`extract_telemetry_snapshot`, `unified_service.TelemetryExtractor`) is unchanged.
- A slice that matches no samples is treated as "no data" and falls into the same enqueue path as a miss, not an empty 200.
- Rows stored before this change have no `elapsed_s` until `populate_telemetry --force` is re-run for that session.

DEFERRED-VM: none.

Needs from orchestrator: nothing new.

## Phase 1d: empty slice, streamed DB-miss, telemetry/summary fix

Status: done, awaiting review. Rebased on v2/integration (4039689) first.

Tests: full suite 295 passed, 2 failed (known pair), 16 skipped. Baseline 289/2/16, so +6, no new failures. Golden default snapshots still pass.

- Empty slice: a stored lap whose `start_m`/`end_m` window matches no sample now returns 200 with empty data in the requested shape (rows: `[]`; columnar: every key with an empty list, including `driver_code`; overlay: per trace). Only a real miss (no stored lap) enqueues. Applies to `telemetry/` and `telemetry/overlay/`; default-path behaviour untouched.
- DB miss with new params: no edit to shared streaming/nonblocking code. `apply_to_stream` (in `telemetry_params.py`) wraps the `StreamingHttpResponse` that `handle_data_request` returns, buffers its single JSON chunk, and applies slice, channel selection and columnar to the task's default-shape rows (`telemetry/` and overlay). Timeout/error chunks and default options pass through unchanged. Limit: the live rows carry no `drs` and, for lap rows from FastF1, only the time the extractor produced, so `channels=drs` is null on a first streamed response (a retry reads stored data and has it).
- `telemetry/summary/` DB path fixed: `session/views.py` never imported `get_telemetry_summary` (every request fell through to the task), the view then serialized a list without `many=True`, and the summary meta had no `limit_max`, which the worker's `LapAnalysisMetaSerializer` requires. Fixes: add the import, `many=isinstance(list)`, and `limit_max` in `get_telemetry_summary`'s meta. Tests `test_summary_serves_stored_telemetry` and `test_summary_worker_serializer_accepts_the_payload` failed before the fix (confirmed) and pass after. start_m/end_m are not added to summary.

## Phase 1e: build fallback per session, no blocking track-map

Status: done, awaiting review. Rebased on v2/integration (6b6e19a). Code-only, tested with fakes; real-data check is DEFERRED-VM.

- Build fallback: `_build_from_any_session` runs the whole build (load, pole lap, telemetry, circuit info) per candidate session in the order Q, SQ, R, S and returns the first that works. A session that loads but is empty (`DataNotLoadedError`, no fastest lap, missing session) is logged and skipped. The task result now includes `session` (the one used); `TrackGeometry.source` already names it. If none works it raises `TrackBuildError` listing each session's reason.
- Failure cache: on `TrackBuildError` the reason is stored in `telemetry_cache` for 300 s (`FAILURE_TTL`); a successful build clears it.
- Endpoints never block on FastF1 now. `track-map/` no longer uses `handle_data_request`/SSE: geometry missing means 202 `{status: pending, task_key, detail}` straight away (build queued), same as mini-sectors and delta. All three share `_missing_geometry`.
- Recent failure: 503 `{status: "failed", error, reason, retry_after}` with a `Retry-After` header, and no enqueue until the TTL passes. 503 over 424: the data source is temporarily unusable and a later retry can succeed, which is what 503 plus Retry-After says; 424 (failed dependency, WebDAV) is rarely understood by clients or proxies, and 500 would suggest a bug. Behaviour change: `track-map/` no longer streams the result on a miss; clients poll or retry.
- Tests (`tests/test_build_fallback.py`, plus the replaced track-map miss test in `test_endpoints.py`): Q loads without laps and R is used; no-fastest-lap and SQ fallback; all unusable records the failure and raises; success clears the failure; 503 with reason and Retry-After on all three endpoints with no enqueue and no FastF1 call; fast 202 on a miss with `SessionManager.get_session` and `fastf1.get_session` patched to raise (never called in the request); enqueue resumes when no failure is recorded.
- Note: my venv lacks `langgraph`, so `api/assistant` tests do not collect here; trackmap suite is 93 passed, rest of the suite run with `--ignore=api/assistant`.
