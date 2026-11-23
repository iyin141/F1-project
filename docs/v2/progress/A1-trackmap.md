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
