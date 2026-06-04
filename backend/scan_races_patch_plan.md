Scan A Patch Plan — RACES canonicalization

Generated: 2026-06-03

Objective: apply minimal, worker-first patches to canonicalize `*_results` task_key/cache_key usage and fix cache API conflicts.

Phases

1. P0 - Cache API consolidation and tests

- Pick canonical cache module: prefer `backend/api/services/cache_service.py` (richer API). Create wrapper in `services/cache.py` that imports and re-exports canonical functions to maintain backward compatibility.
- Update all call sites to import from `services/cache_service.py` where feasible.
- Run tests and fix signature mismatches.

2. P0 - TaskRecord migration strategy

- Create a management command `migrate_taskrecord_keys` under `backend/api/management/commands/` that maps legacy `populate_*` keys to canonical `*_results` aliases; the command performs dry-run and optional in-place rename.
- Alternatively, update `TaskManager` to treat `populate_*` and canonical equivalents as aliases when deduping.

3. P1 - Rename `practice` enqueue

- Edit `backend/api/results/services/practice.py` to create `task_key` `practice_results:...` and ensure `cache_key` also uses `practice_results`.

4. P1 - Update enqueue call sites

- Replace literal `populate_*` task_key constructions across views and services; prefer passing explicit `task_key` param to `handle_data_request` and TaskManager.enqueue.
- Files: `backend/api/views.py`, `backend/api/results/services/*.py`, `backend/api/constructors/*`.

5. P2 - Update workers/tests

- Adjust any worker that expects old `populate_` TaskRecord rows to accept canonical keys or handle aliasing.
- Update tests to assert canonical keys where appropriate; where tests assert exact strings, update test expectations.

6. P2 - Verification & rollout

- Run unit tests, run integration tests (SSE), manual smoke test with a small dataset.
- Deploy worker-first rolling update to avoid lost in-flight TaskRecord expectations.

Example patches to apply (concrete)

- Create small wrapper file `backend/api/services/cache_compat.py`:
  - import canonical functions from `cache_service.py` and re-export under old names.

- Update `practice.py` change `task_key` string prefix.

Detected race-related workers

- `backend/api/workers/tier2_fast/populate_race_results.py`
- `backend/api/workers/tier3_medium/populate_positions.py`
- `backend/api/workers/tier3_medium/populate_laps.py`
- `backend/api/workers/tier3_medium/populate_drs.py`
- `backend/api/workers/tier3_medium/populate_track_status.py`
- `backend/api/workers/tier2_fast/populate_pit_stops.py`
- `backend/api/workers/tier2_fast/populate_incidents.py`
- `backend/api/workers/tier1_instant/populate_standings.py`
- `backend/api/workers/tier2_fast/seed_historical_round.py`
- `backend/api/workers/tier2_fast/prefetch_race_weekend.py`

Plan change for race workers

- Treat the above as in-scope for the RACES canonicalization. For each worker:
  - Ensure the worker publishes a `cache_key` and `task_key` that follow the canonical naming (prefer `*_results` or a documented canonical prefix for the data type).
  - Prefer worker-first edits: update worker to set canonical `cache_key`, then update enqueue call-sites to pass matching `task_key`.
  - If renaming the task_key would break dedupe, implement TaskManager aliasing or run the `migrate_taskrecord_keys` management command before switching consumers to the new key.

Estimated effort: 2-4 hours for code edits + 1-2 hours for testing and migration command.

Approval:

- Reply with 'apply' to run worker-first patch sequence now, or 'report-only' to stop here and review the three deliverables.
