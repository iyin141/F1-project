# File usage (request handling)

## In-use (High confidence)

- backend/f1_project/wsgi.py
- backend/f1_project/asgi.py
- backend/f1_project/urls.py
- backend/f1_project/settings.py
- backend/api/urls.py
- backend/api/views.py
- backend/api/services/nonblocking.py
- backend/api/services/unified_service.py
- backend/api/queue/manager.py
- backend/api/tasks.py
- backend/api/services/streaming.py
- backend/api/auth.py
- backend/api/permissions.py
- backend/api/throttling.py
- backend/api/exception_handlers.py
- backend/api/serializers.py
- backend/api/common/request_id.py
- backend/api/middleware/csrf_exempt.py

## In-use (Medium confidence)

- backend/api/middleware/no_cache.py (used by some views/mixins)
- backend/api/services/pubsub.py (redis pubsub used by streaming)
- backend/api/services/cache_service.py

## Likely unused (Low confidence)

- backend/scripts/\* (utility scripts)
- backend/docs/\* (documentation files)
- backend/api/fixtures/\* (test fixtures)
- backend/f1_cache/ (cached FastF1 picks; used at runtime by fastf1 only)

## Tests and fixtures

- backend/api/tests/\* (unit/integration tests) — not used at runtime
- test_unified_load_requirements.py — test harness

Notes: This is a best-effort static analysis based on code inspection. Dynamic imports, runtime configuration, or environment-specific modules may change actual usage. Next step: run a static grep to enumerate all `path(` and `include(` usages in `backend/api/urls.py` and cross-check imports to populate `docs/endpoint_map.csv` fully.
