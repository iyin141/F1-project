**Non-Blocking Request Flow (Redis Pub/Sub + Celery)**

- **Goal:** Ensure HTTP request handlers never block on heavy work (e.g., FastF1). Waiters subscribe to a Redis pub/sub channel for a task, receive small META diagnostics and READY/FAILED signals from workers, then read cached payload and return merged meta.

**Files:**

- [backend/api/services/nonblocking.py](backend/api/services/nonblocking.py)
- [backend/api/queue/manager.py](backend/api/queue/manager.py)

**Sequence Diagram (mermaid)**

```mermaid
sequenceDiagram
    participant Client
    participant HTTP as API (waiter)
    participant Redis
    participant TaskMgr as TaskManager
    participant Worker as Celery Worker
    participant Cache
    participant DB

    Client->>HTTP: GET /resource (cache_key, task_key)
    HTTP->>Cache: GET cache_key
    alt cache hit
        Cache-->>HTTP: payload
        HTTP-->>Client: 200 payload
    else cache miss
        HTTP->>DB: db_fetch_fn() (sync_to_async)
        alt db hit
            DB-->>HTTP: db payload
            HTTP->>Cache: set cache_key (backfill)
            HTTP-->>Client: 200 payload
        else db miss
            HTTP->>TaskMgr: get_existing_task(task_key)
            alt task exists
                TaskMgr-->>HTTP: task exists
            else enqueue
                HTTP->>TaskMgr: enqueue_if_needed(task_key)
                TaskMgr-->>HTTP: task enqueued
            end
            HTTP->>Redis: SUBSCRIBE channel:task_key
            loop wait (deadline)
                Redis-->>HTTP: {event: META, meta: {...}} OR READY OR FAILED
                alt META
                    HTTP: buffer small META (<=4096 bytes)
                else READY
                    HTTP->>TaskMgr: get_task_details(task_key)  %% persisted meta
                    HTTP->>Cache: GET cache_key
                    alt cache hit
                        Cache-->>HTTP: payload
                        HTTP: merge (buffered_meta | persisted_meta) into payload.meta
                        HTTP-->>Client: 200 payload_with_meta
                        break
                    else poll short loop for cache
                        Cache-->>HTTP: payload (if appears)
                        HTTP: merge meta and return 200
                    end
                    HTTP->>Client: if no payload but meta -> 200 with meta diagnostics
                else FAILED
                    HTTP->>TaskMgr: get_task_details(task_key)
                    HTTP-->>Client: 500 + details
                end
            end
            HTTP-->>Client: 504 with buffered/persisted meta if timeout
        end
    end

    Note over Worker,TaskMgr: Worker produces results, saves payload to Cache, and calls TaskManager.mark_complete(..., meta)
    Worker->>Cache: SET cache_key = payload
    Worker->>TaskMgr: mark_complete(task_key, meta)
    TaskMgr->>DB: persist TaskRecord.meta
    TaskMgr->>Redis: PUBLISH channel:task_key {event: "META", meta: {...}}
    TaskMgr->>Redis: PUBLISH channel:task_key "READY"
```

**Detailed step-by-step flow**

- 1. HTTP waiter receives request with `cache_key` and `task_key`.
  - a) Fast path: do a Redis `GET` for `cache_key`. If present, return immediately (200).
  - b) DB fallback: call `db_fetch_fn()` (bridged with `sync_to_async`). If DB data exists, backfill cache and return (200).
  - c) Task coordination: check `TaskManager.get_existing_task(task_key)`. If not present, `enqueue_if_needed()`.

- 2. Subscribe to `channel:{task_key}` and enter wait loop until deadline.
  - a) On `META` event (JSON with event=="META"), the waiter buffers small meta (<= 4096 bytes) and does not perform cache/DB reads in the META handler (to avoid extra GETs).
  - b) On `READY` event, waiter proactively:
    - reads persisted details via `TaskManager.get_task_details(task_key)` (to pick up persisted meta if any),
    - performs a `GET cache_key` and a short poll loop (a few tries with small sleep) to let the worker populate cache,
    - if payload appears, merge payload.meta (if any) with buffered/persisted meta (buffered takes precedence for fields), call `_ensure_readiness_for_payload()`, and return 200 with merged payload.
    - if no payload but meta exists (buffered or persisted), return 200 with diagnostic `meta`.
  - c) On `FAILED` event, return 500 with `TaskManager.get_task_details(task_key)` in the body.
  - d) On deadline (timeout), return 504 with any buffered or persisted meta included.

**Worker / TaskManager responsibilities**

- Worker (Celery):
  - Execute heavy computation (e.g., FastF1) strictly in worker process (never synchronously on HTTP thread).
  - When ready, write payload to cache (SET `cache_key` -> payload).
  - Call `TaskManager.mark_complete(task_key, meta=...)` (or equivalent) which:
    - persists `TaskRecord.meta` in DB,
    - publishes a small `{event: "META", "meta": ...}` on `channel:{task_key}` (bounded size), and
    - publishes `"READY"` on `channel:{task_key}` to wake waiters.

- TaskManager:
  - Centralizes enqueue/get/mark_complete logic in [backend/api/queue/manager.py](backend/api/queue/manager.py).
  - Persists meta reliably so late-arriving waiters can still see diagnostics even if they missed the transient META pub/sub.

**Waiter semantics (key design constraints)**

- Buffer only small META payloads (<=4096 bytes). Do not perform cache/DB reads during META handling.
- On READY, prefer to return merged payload (payload.meta + buffered/persisted meta) when cache contains data.
- If READY arrives but cache not populated, poll briefly, then return meta diagnostics if payload still missing.
- On FAILED, surface TaskRecord details to the caller as a 500.
- On timeout, return 504 with `meta` diagnostics if available.

**Testing notes**

- Unit tests use `FakeRedis` + `FakePubSub` to emulate pub/sub and cache behavior. Tests exercise paths: META→READY→payload, READY→persisted-meta→payload, only META→timeout-with-meta.
- Tests should run under a single event loop (use `pytest-asyncio` or ensure `sync_to_async(..., thread_sensitive=False)` for non-ORM sync calls).

**Troubleshooting & recommendations**

- Ensure workers always write cache _before_ publishing `READY`. Waiters rely on short poll after READY.
- Persist meta in `TaskManager.mark_complete` to provide late-arriving waiters with diagnostics.
- Avoid calling FastF1 or other heavy sync code from HTTP threads — always delegate to Celery workers.
- Keep META messages compact; use DB-persisted `TaskRecord.meta` for large traces.
- Consider adding a telemetry/trace id in pubsub messages so waiters can correlate events across retries and clients.

---

If you want, I can:

- remove debug traces from `nonblocking.py`,
- create a simplified PNG/SVG version of this flow (exported from Mermaid), or
- add this doc to README/Docs index.
