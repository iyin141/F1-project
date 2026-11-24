# D1 docs: progress

Phase 4 (README, architecture diagram, Python client). Status: done, awaiting review. Branch `v2/docs` from `v2/integration` 486f90a.

## Files
- `README.md` (new; the repo had none). Sections as briefed: what and why, diagram, quick start, endpoint table, three curl calls, design decisions, performance, Chaos Point model card, Stewards results, MCP, client, testing, "where AI helped / what I rejected", DEFERRED-VM table.
- `docs/v2/diagrams/architecture.json` + `architecture.svg`: Archify architecture diagram. Archify's `export-svg` needs no network or install (Node 24 only); the JSON was written from `docker-compose.yml` and the Celery routing, validated (0 errors, 2 warnings), and the SVG was rendered and looked at (Edge headless screenshot). The boundary box wraps clients and external services out, but the `claude` CLI really runs inside the `worker-rag` container; the diagram shows it as external because the subscription is.
- `clients/python/`: `f1controlroom` 0.1.0, MIT, `pyproject.toml`, `README.md`, `tests/` (19, mocked `httpx.MockTransport`).

## Client design
- httpx over requests: streaming for SSE, a built-in mock transport, one dependency.
- 202: raises `PendingError(task_key)` by default; `wait=` (per call or on the client) polls with Retry-After, else 2 s, then `PendingTimeout`.
- 503: waits Retry-After (capped 30 s), retries `retries` times (default 2), then `ServiceUnavailable`.
- v1 views answer 200 `text/event-stream` with one frame on a miss; the client returns that frame's JSON.
- `ask()` yields SSE events and resumes through `/ask/<task_key>/events` with `Last-Event-ID` after a dropped connection (tested without repeating tokens).
- Verified: installed into a clean venv with `pip install ".[test]"`, 19 passed. Not published.
- Not covered: an async client, typed response models (responses are decoded JSON), the POST auth endpoints.

## Verification
- Backend suite from `backend/`, own venv (requirements-dev + requirements-rag + fastembed 0.9.1, FastF1 per requirements): **715 passed, 21 skipped, 0 failed**, 200 s. Ruff clean. The brief said "about 572 tests"; the suite has grown, so README quotes 715.
- pip on this Windows machine hit WinError 32 file locks during install (an earlier detached pip run overlapped); a retry loop fixed it. Not a repo issue.

## Measured vs placeholder in the README
- Measured, cited: telemetry 51.5 / 13.6 / 4.9 KB and route latencies (API test), A1 fixture table, retrieval recall/MRR per mode, e2e (9/10, 1.0, 0.70, 2/2, $0.4479, 77.5 s median), test count (just run).
- Placeholder or absent, stated as such: Chaos Point backtest metrics and calibration plot (none exist), hero GIF, any VM or arm64 number, cache hit rates.

## Open questions for the orchestrator
1. `README.md` was orchestrator-owned per ORCHESTRATION.md; the brief assigned it to D1, so it is written here. Merge as you see fit.
2. License section says "see the repository licence" because the repo has no LICENSE file; the client has its own MIT file. Add a root licence?
3. `.github/workflows/ci.yml` is the old workflow (Python 3.12, `manage.py test`, no rag deps) and runs alongside `docker.yml`. Remove or align it?
4. `docs/v2/openapi-v2.yaml` does not list `chaos/circuits/`, `chaos/circuits/summary/`; regenerate it from `/api/schema/` so the client and README match.
5. Brief said the FIA-terms decision was approved by the user for public use; the README states that as the owner's approval. Confirm the wording is what you want public.
6. MCP compose service is still not wired (A3 3e). README says so.
7. Hero GIF needs the UI.
