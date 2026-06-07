SERVER RESPONSES (200, 202, errors)

Overview

- Non-blocking endpoints return either HTTP 200 (data available) or HTTP 202 (background work enqueued / in-flight).
- Errors return 4xx/5xx as appropriate (validation 400, enqueue failure 500).

200 OK (examples)

- Source: cache or DB
- Body shape (from `build_nonblocking_response_200()` / `await_or_enqueue_data()`):

```json
{
  "source": "cache",
  "data": {
    /* payload */
  },
  "meta": {
    /* optional context */
  }
}
```

- When returned from DB, `source` is `database` and response is backfilled into Redis for future hits.

202 Accepted (examples)

- Triggered when data is not available immediately and a background task is queued or already running.
- Body shape (from `build_nonblocking_response_202()` / `await_or_enqueue_data()`):

```json
{
  "status": "enqueued",
  "task_id": "<celery-uuid>",
  "task_key": "seed_round:2026:4",
  "estimated_wait_seconds": 45,
  "queue_depth": 5,
  "poll_url": "/api/tasks/<celery-uuid>/status/"
}
```

Error cases

- 400 Bad Request: validation errors (e.g., invalid year) returned with `error` and `message` fields.
- 500 Internal Server Error: enqueueing failed or unexpected errors; body contains `error`, `detail`, `task_key` when applicable.

Polling

- `GET /api/tasks/{task_id}/status/` reads `task_status:{task_id}` from Redis and falls back to `TaskRecord` in DB if Redis unavailable.
- Poll response returns the current `status` and optionally timestamps or `error_message` for diagnostics.

Best practices for clients

- If 202 returned: poll `poll_url` or subscribe to events; avoid tight polling loops (use exponential backoff).
- On 200: use data immediately and avoid triggering an expensive reload; cache TTLs are set in `cache_service.get_cache_ttl()`.

References

- `backend/api/services/nonblocking.py`
- `backend/api/services/cache_service.py`
- `backend/api/queue/manager.py`
