# v2 orchestration contract (read before any edit)

Several agents build F1 Control Room v2 in parallel, one branch each. An
orchestrator reviews every phase and does every merge. This file is the
contract that keeps the branches from colliding. If a rule here blocks you,
stop and report it; do not work around it.

Plans: `docs/v2/ARCHITECTURE_V2.md`, `docs/v2/plans/00_*.md` (libraries),
`01_*.md` (backend), `02_*.md` (UI). Where this file and a plan disagree,
this file wins.

## Branches

| Agent | Branch | Worktree | Scope |
|---|---|---|---|
| orchestrator | `v2/integration` | `F1-project/wt/integration` | scaffold, shared files, merges |
| A0 infra | `v2/infra` | `F1-project/wt/infra` | plan 01 Phase 0 (hygiene + Docker port) |
| A1 trackmap | `v2/trackmap` | `F1-project/wt/trackmap` | plan 01 Phase 1 |
| A2 chaos | `v2/chaos` | `F1-project/wt/chaos` | plan 01 Phase 2 |
| A3 stewards | `v2/stewards` | `F1-project/wt/stewards` | plan 01 Phase 3 + MCP |

All branches start from `v2/integration`. Work only inside your own worktree.
Never `git checkout` another branch, never merge, never push, never touch
another worktree or the original checkout `F1-project/f1-project-backend`.

## File ownership

| Paths | Owner |
|---|---|
| `backend/Dockerfile*`, `backend/.dockerignore`, `backend/docker/`, `docker-compose*.yml`, `deploy/`, `Makefile`, `.github/`, `.gitignore`, `.env.example`, moving root `test_*.py` / `warmup_cache.py`, removing `misc_2/` | A0 |
| `backend/api/trackmap/**`; the optional new query params on existing telemetry views (`backend/api/session/views.py`, `backend/api/services/analysis.py`, `backend/api/services/unified_service.py`) | A1 |
| `backend/api/chaos/**` | A2 |
| `backend/api/assistant/**`, `backend/stewards_mcp/**` | A3 |
| `backend/requirements.txt`, `backend/f1_project/**`, `backend/api/urls.py`, `README.md`, this file | orchestrator only |
| `docs/v2/progress/<your-agent>.md` | that agent |

Everything not listed is read-only. Need a change outside your paths (a new
dependency, a setting, a shared helper)? Write it under "Needs from
orchestrator" in your progress file and carry on with what you can.

New dependencies: list them, pinned, in `backend/api/<your-app>/NEEDS.md`
(A0: in your progress file). Install them into your own venv. The orchestrator
moves them into `requirements.txt` at merge.

## Already wired (do not re-wire)

- Apps registered in `INSTALLED_APPS` with their own labels, so each has its
  own `migrations/` folder: `trackmap`, `chaos`, `assistant`. Models go in
  `api/<app>/models.py`; run `makemigrations <label>` only for your label.
- URLs (in `api/urls.py`):
  - `analysis/races/<int:year>/<int:round_number>/` + `api.trackmap.urls`
    (your views receive `year` and `round_number` kwargs; add
    `track-map/`, `mini-sectors/`, `telemetry/delta/`)
  - `chaos/` + `api.chaos.urls`
  - `assistant/` + `api.assistant.urls`
- Celery queues `ml` and `rag` are declared. Routing is by module, set in
  `CELERY_TASK_ROUTES`:
  - `api.trackmap.tasks.*` to `tier4_telemetry`
  - `api.chaos.tasks.*` to `tier3_medium`
  - `api.chaos.ml_tasks.*` to `ml`. **torch / sdm imports live only in this module**, imported lazily inside task bodies.
  - `api.assistant.tasks.*` to `rag`

## Runtime isolation

- Own venv: `python -m venv .venv` in your worktree's `backend/`, then
  `pip install -r requirements.txt` plus your NEEDS. Never pip-install into
  `F1-project/f1-project-backend/backend/venv`.
- Tests: from `backend/`, load the original env into the shell without
  reading or printing it, then run pytest:
  `python -c "import dotenv,sys,pytest; dotenv.load_dotenv(r'C:/Users/iyino/Videos/F1-project/f1-project-backend/backend/.env'); sys.exit(pytest.main(['-q','-p','no:cacheprovider']))"`
  (do NOT `source` the file in a shell: values contain shell metacharacters and the error prints them)
  (`settings_test` swaps the database to SQLite and caches to memory). Never
  `cat`, copy, echo or commit `.env` values. Never connect to Neon. Without
  this env the suite shows 72 false failures (401s: the tests need the real
  `INTERNAL_API_KEY` setup). A0 fixes this in Phase 0 so tests run with no `.env`.
- Dev servers and containers, if you need one: A1 port 8001, A2 port 8002,
  A3 port 8003; A3 local Postgres+pgvector on 5433. Docker Compose project
  name `f1-<agent>` (`docker compose -p f1-trackmap ...`).
- Test baseline on `v2/integration` (2026-11-23): 210 passed, 2 failed,
  16 skipped. The 2 failures are pre-existing (`test_driver_endpoints.py`
  readiness tests make a live Jolpica call through a proxy that returns
  402). Your phase must not add failures.

## Hard rules (from plan 01)

- Additive only. No existing URL, serializer field, model or default
  response changes. New optional query params must give byte-identical
  default output; prove it with a test.
- Torch never loads in the web process.
- No secrets in the repo.
- No live network calls in tests (FastF1, Jolpica, Hugging Face, FIA,
  `claude`). Use fixtures and fakes.

## Deferred: needs the Oracle VM (do not attempt unless it blocks you)

- Running the stack on the VM, VM acceptance checks, arm64 runtime checks.
- Kumo Tabular smoke test, weight download, real Kumo inference and backtests.
- Enabling pgvector on Neon (production DB).
Build the code paths and tests for these, mark them `DEFERRED-VM` in your
progress file, and move on. If something genuinely blocks a phase, stop and
report it instead.

## LLM calls: Claude headless (Stewards, and any LLM-judged eval)

No API key. The LLM is the `claude` CLI run headless on the logged-in
subscription, as a subprocess, following the reference implementation in
`C:/Users/iyino/Videos/stock-index-project/services/rag-pipeline/rag_pipeline/claude_headless.py`
and `langchain_adapter.py` (read them; reimplement, do not import):

- argv: `claude -p --output-format json --json-schema <inline json> --model <id> --append-system-prompt <text>`; prompt on stdin; `cwd` an empty temp dir.
- Never `--bare` (it ignores the subscription login).
- On Windows, resolve the real `claude.exe` behind the npm shim (`resolve_claude_binary`).
- Classify errors: rate limit (retry with backoff), auth expired (never retry), bad JSON (retry once), timeout.
- Wrap as a LangChain `RunnableLambda` so LangGraph nodes can call it.
- In Docker, the container mounts the host's `~/.claude` (see that project's `docker-compose.yml`, `CLAUDE_CONFIG_DIR`), and the image installs the CLI with npm.
- Verify every flag against `claude --help` on this machine before use (for example whether `--output-format stream-json` gives token streaming for SSE). Do not trust memory.
- Live `claude` calls cost the user's subscription: at most 5 live calls per phase for smoke checks. Tests use a fake runner.

## Phase protocol

1. Do exactly one phase (the orchestrator names it), then stop.
2. Commit on your branch in small commits. No Claude co-author or attribution lines in commit messages.
3. Update `docs/v2/progress/<agent>.md` with: phase, status, commits,
   files touched, test result (counts), what is DEFERRED-VM, open questions,
   "Needs from orchestrator".
4. Your final message is the report: the same content, short.
5. Before starting the next phase, the orchestrator tells you to rebase on
   `v2/integration`: `git fetch` is not needed (same repo), use `git rebase v2/integration`.
