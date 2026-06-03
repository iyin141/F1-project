WORKER DETAILS

Overview

- Workers: Celery processes started in `start_prod.sh` with per-tier queues (tier1_instant, tier2_fast, tier3_medium, tier4_telemetry, tier5_pagination, tier6_notifications, backfill).
- Tasks implemented as `@shared_task` functions under `backend/api/workers/` and higher-level tasks in `backend/api/tasks.py`.

Responsibilities

- Pick up Celery tasks from specific queues and run business logic (DB writes, backfills, external API calls).
- Coordinate with `TaskManager` to update lifecycle states (`mark_running`, `mark_complete`, `mark_failed`).
- Backfill Redis cache keys via `api.services.cache_service.set_cache()` after a successful write.
- Log lifecycle events (`event=celery_start`, `event=celery_success`, `event=celery_failed`) for observability.

Key integrations

- `TaskManager` (`backend/api/queue/manager.py`): workers call `TaskManager.mark_running(task_key)`, `mark_complete(task_key)`, or `mark_failed(task_key, exc)` during execution.
- Redis cache (`django.core.cache`): workers write cached payloads and clear load locks; use `set_task_status()` to update `task_status:{task_id}` keys.
- Database (Postgres): workers persist computed data and update `TaskRecord` entries.

Operational notes

- Concurrency and queue assignment are tuned per `start_prod.sh` (see worker concurrency and queue names).
- Workers should ensure DB writes are committed before calling `mark_complete()` to avoid race conditions.
- On exception, capture traceback and call `mark_failed()` so the `TaskRecord.error_message` is populated for diagnostics.

Quick examples

- Worker start (production):
  - `celery -A f1_project worker --loglevel=info --concurrency=6 -Q tier1_instant -n worker_tier1@%h --detach`

- Typical worker flow (pseudo):
  1. `TaskManager.mark_running(task_key)`
  2. Execute work (DB writes, external calls)
  3. On success: `TaskManager.mark_complete(task_key)` + `cache_service.set_cache(...)`
  4. On failure: `TaskManager.mark_failed(task_key, exc)`

References

- `backend/api/workers/`
- `backend/api/queue/manager.py`
- `backend/api/services/cache_service.py`
