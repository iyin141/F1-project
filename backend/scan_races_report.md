Scan A — RACES actionable report

Generated: 2026-06-03

High-level findings

- Many callers still enqueue tasks with `populate_...` literal task_key strings (views and some generic views). These create TaskRecord rows with legacy keys.
- Worker `populate_race_results` already writes canonical `cache_key` values (`race_results:{year}:{round}`) via `worker_utils.handle_result()` in most cases.
- `practice` service currently enqueues `practice:{year}:{round}:{session}` (legacy) — should be `practice_results:{year}:{round}:{session}`.
- There are two `get_from_cache` variants (`services/cache.py` and `services/cache_service.py`) with mismatched signatures; logs show runtime errors from this conflict.

Priority items (P0..P2)

- P0: Consolidate cache API and fix `get_from_cache` signature mismatches (high risk; causes exceptions). Files: `backend/api/services/cache.py`, `backend/api/services/cache_service.py`, `backend/api/views/cache_decorators.py`, `backend/api/results/repository.py`.
- P0: Data migration for existing TaskRecord rows that use `populate_*` prefix to add canonical alias rows or rename keys. (Plan drafted in patch plan.)
- P1: Fix `practice` service enqueue to use `practice_results` canonical key. File: `backend/api/results/services/practice.py` (line ~150).
- P1: Update any views using `task_key=f"populate_..."` literals to instead pass explicit canonical `task_key` (e.g., `race_results:{year}:{round}`) when calling `handle_data_request`. Files: `backend/api/views.py` (multiple), `backend/api/results/views.py` (confirmed uses canonical but others still use populate\_ literals).
- P2: Ensure TaskManager/TASK_TIER_MAP accommodates canonical names or map worker names consistently. File: `backend/api/queue/manager.py`.

Per-file quick actions (examples)

- `backend/api/results/services/practice.py` L150: change
  - from: `task_key=f"practice:{int(year)}:{int(round_number)}:{normalized_session}"`
  - to: `task_key=f"practice_results:{int(year)}:{int(round_number)}:{normalized_session}"`

- `backend/api/views.py` many lines: replace `task_key=f"populate_*:{...}"` with canonical equivalents or pass the canonical `task_key` variable into `handle_data_request` calls.

- `backend/api/services/cache.py` / `backend/api/services/cache_service.py`: choose one `get_from_cache` signature and update callers.

Verification checklist per fix

- Unit test updates (where tests expect old keys). Relevant tests: `test_session_canonicalization_more.py`, `test_session_canonicalization.py`, `test_tier2_workers.py`.
- Runtime: start Django & Celery, call endpoint via SSE, verify Redis key exists (`race_results:YYYY:RR` or `practice_results:...`) and SSE client receives payload.

Deliverables

- `backend/scan_races_raw.json` (raw summary)
- `backend/scan_races_report.md` (this file)
- `backend/scan_races_patch_plan.md` (next)
