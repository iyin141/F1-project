# Build Prompt 1 of 6: F1 Control Room Backend (Docker port + v2 additions)

## Role and goal

You are a senior backend engineer extending **F1 Control Room**, an open-source Django API that serves live and historical F1 data from FastF1 and Jolpica. Your job:

1. Port the whole stack to Docker.
2. Add three features without changing any existing route or response: track map and mini-sectors, the Chaos Point predictor, and the Stewards assistant.

Work in small, reviewable commits. After each phase, run the existing test suite (214 tests) and add tests for new code.

Load these skills first (see `00_RESOURCES_AND_SKILLS.md`): `claude-api`, `mcp-builder`, `archify` (for the README architecture diagram).

## Hard rules

- **Additive only.** No existing URL, serializer field, model or response shape changes. Existing endpoints may only gain new **optional** query parameters, and their default must give today's output byte-for-byte.
- **Torch never loads in the web process.** ML runs only in the `worker-ml` container.
- Every image builds for **linux/arm64**. The server is Oracle A1 Flex: 4 ARM cores, 24 GB RAM.
- **Postgres stays on Neon** (external). Don't add a Postgres container for production. One is allowed in `docker-compose.dev.yml` only.
- No secrets in the repo. Everything comes from `.env`, and `.env.example` is committed.

## Current system (read the code to confirm)

- Django 6 + DRF, ASGI under uvicorn (2 workers) for SSE streaming. Routes are mounted at `/api/` (`api/urls.py`). Docs are at `/api/docs/` (drf-spectacular).
- Celery queues and workers (from `start_prod.sh` and `f1_project/celery.py`):

  | Queue | Concurrency | Memory cap |
  |---|---|---|
  | `tier1_instant` | 4 | |
  | `tier2_fast` | 4 | |
  | `tier3_medium` | 4 | about 125 MB per child |
  | `tier4_telemetry` | 3 | about 366 MB per child |
  | `tier6_notifications` | 2 | |

  Plus beat and flower.
- **Bug to fix:** `tier5_pagination` and `backfill` are declared in `celery.py`, but no worker consumes them, so any task routed there never runs.
- Redis: four logical caches (`REDIS_1_URL` to `REDIS_4_URL`). Redis 3 is the Celery broker.
- Patterns to reuse:
  - `api/services/nonblocking.py`: returns 200 JSON, or SSE with task progress.
  - `api/services/streaming.py`: SSE.
  - `api/throttling.py`: `APIKeyThrottle` tiers.
  - Payload tables in `api/models/unified.py`: `PitStopData`, `IncidentData`, `TrackStatusData`, `PositionData`, `DRSData`, `WeatherData`.
- Telemetry currently uses `lap.get_car_data().add_distance()`, which has no X/Y. Distance-window slicing already exists in `api/services/analysis.py` and `unified_service.py`.

## Phase 0: Repo hygiene and Docker port

**Hygiene**

1. Make `main` the default branch and tag `v1.0` before changes.
2. Untrack and gitignore: `backend/test_db.sqlite3`, `backend/logs/`, `backend/misc/*.txt`, `backend/celerybeat-schedule*`, `misc_2/`.
3. Move root `test_*.py` and `warmup_cache.py` into `backend/api/tests/` or `backend/scripts/`.
4. Move `git-filter-repo` and `GitPython` out of runtime requirements. Pick Celery and drop `django-background-tasks` if it's unused (grep first).

**Docker**

5. `backend/Dockerfile`:
   - multi-stage, `python:3.12-slim`, arm64-safe;
   - non-root user;
   - `pip install --no-cache-dir`;
   - `FASTF1_CACHE` on a volume;
   - healthcheck on `/api/` readiness.
6. `backend/Dockerfile.ml`: extends the base image and adds `torch` (CPU, aarch64) and `structured-data-models`, with a weights volume at `/models`.
7. `docker-compose.yml` services:

   ```
   web            uvicorn f1_project.asgi:application --workers 2 (port 8000, internal)
   worker-t1      celery -Q tier1_instant -c 4
   worker-t2      celery -Q tier2_fast -c 4
   worker-t3      celery -Q tier3_medium -c 4 --max-memory-per-child=128000
   worker-t4      celery -Q tier4_telemetry -c 3 --max-memory-per-child=375000
   worker-t5      celery -Q tier5_pagination,backfill -c 2      # fixes the orphan queues
   worker-t6      celery -Q tier6_notifications -c 2
   worker-ml      celery -Q ml -c 1          (Dockerfile.ml)
   worker-rag     celery -Q rag -c 2
   beat           celery beat
   flower         celery flower (behind nginx basic auth)
   redis          redis:7-alpine, appendonly, maxmemory 1.5gb (keeps the 4 logical DBs)
   nginx          reverse proxy, gzip/brotli, SSE-friendly (proxy_buffering off on stream routes)
   frontend       (see Prompt 2)
   ```

8. `docker-compose.dev.yml`: adds `postgres:16` with pgvector and mounts the source for hot reload.
9. `entrypoint.sh`: wait for the database, run `migrate`, run `collectstatic`, then `exec "$@"`.
10. Set `deploy.resources.limits.memory` per service to match the memory budget in `start_prod.sh`. The total must stay under about 12 GB, leaving headroom.
11. `Makefile`: `make up`, `make down`, `make logs s=web`, `make test`, `make migrate`, `make shell`.
12. CI:
    - build both images for arm64 with buildx;
    - run pytest inside the image;
    - add ruff;
    - add a status badge to the README.

**Acceptance:** `docker compose up -d` on the VM serves every existing endpoint with identical responses (snapshot-test 10 representative routes before and after). Flower, beat and all queues are healthy. `start_prod.sh` is kept, but documented as legacy.

## Phase 1: Track map, mini-sectors, delta (new app `api/trackmap/`)

**Model**

`TrackGeometry` fields: `circuit_key`, `year`, `layout_hash`, `points` (columnar x/y/z/distance), `corners`, `mini_sectors`, `drs_zones`, `source`, `created_at`.
- Unique on `(circuit_key, layout_hash)`.
- Build the points from the pole lap with `lap.get_telemetry()`, which merges position and car data. Downsample to about 1,500 points with Douglas-Peucker or a fixed distance step.
- `corners` come from `session.get_circuit_info()` (number, letter, angle, distance, x, y).
- `mini_sectors`: 25 equal-distance segments by default. Add corner-anchored segments as `?scheme=corners`.
- `drs_zones` are derived from the pole lap's DRS channel.

**Task**

`build_track_geometry(year, round)` on `tier4_telemetry`, triggered after session ingestion. Cache permanently in Redis 2, keyed by `layout_hash`.

**Endpoints** (GET, `APIKeyThrottle`, `nonblocking` pattern when not yet built)

- `/api/analysis/races/<y>/<r>/track-map/?scheme=distance|corners`
- `/api/analysis/races/<y>/<r>/mini-sectors/?drivers=VER,NOR&lap=fastest|<n>`: per-segment times per driver, the fastest driver per segment, and gaps.
- `/api/analysis/races/<y>/<r>/telemetry/delta/?ref=VER&cmp=NOR&lap=fastest`: delta time by distance, interpolated onto a common distance grid.

**Optional parameters on existing telemetry endpoints** (default output unchanged)

- `start_m`, `end_m`
- `channels=speed,throttle,brake,gear,rpm,drs`
- `format=columnar`

Measure payload size and latency before and after, and put the numbers in the README.

**Tests:** geometry closes into a loop, mini-sector times add up to the lap time within tolerance, columnar and row formats contain identical values, and default responses match the snapshots.

## Phase 2: Chaos Point (new app `api/chaos/`)

### Targets

Per race, per driver-race and per 5-lap window:
- `sc_vsc_red`
- `dnf_mechanical`
- `dnf_incident`
- `slow_stop` (stationary or pit-lane time above that season's 90th percentile)
- `unlucky_stop` (pitted under green within 2 laps before an SC or VSC)

The **Chaos Index** is the expected number of disruptive events in the race, computed from calibrated probabilities. Show "unlucky stop" as a team or driver tendency with intervals, never as a skill score.

### Tables

- `CircuitProfile`: type (street, permanent or hybrid), length, number of corners, wall-proximity proxy, overtaking index, elevation range.
- `RaceEventLabel`: year, round, lap, driver, team, type, source.
- `FeatureSet`: version, path to the Parquet file, column list, row count.
- `ModelRun`: model, size, context rows, metrics JSON, calibration JSON, git SHA, created.
- `ChaosPrediction`: year, round, scope, entity, target, probability, p10, p90, model run.

### Pipeline

A Celery chain, run by beat on Wednesday before each race and after each race:

1. `build_labels` (`tier3_medium`):
   - safety car, VSC and red flag from `TrackStatusData` codes 4, 6 and 5, cross-checked with race-control messages;
   - DNF groups from the result status strings, mapped into engine, gearbox, hydraulics, electrical, brakes, accident, collision and other (keep the mapping in a versioned YAML);
   - slow and unlucky stops from `PitStopData` and the track-status timeline.
2. `build_features` (`tier3_medium`):
   - numeric-only features, because Kumo needs them: circuit profile, the season, the era flag (2022 regulations), weather, grid position, team and driver historical rates (computed leakage-free, using only races before this one), lap-window index, and whether the window is lap 1 or a restart;
   - one-hot or ordinal encode categoricals;
   - write Parquet to the `/features` volume and register a `FeatureSet`.
3. `run_baseline` (`tier3_medium`): hierarchical Beta-Binomial, with circuit shrunk to circuit type to global, and driver shrunk to team to global.
4. `run_kumo` (`ml` queue):

   ```python
   from sdm.models import KumoTabular
   model = KumoTabular(size="small", device="cpu")   # benchmark small vs medium on the VM
   model.fit(x=X_context, y=y_context)               # in-context: no gradient training
   proba = model.predict_proba(X_query)              # confirm exact method names in the sdm docs
   ```

   - Pretraining covers up to 60,000 rows and 100 columns, so stay under both: use lap windows, not raw laps, and sample the context if needed.
   - Weights download from Hugging Face on first run, so persist `/models`.
   - Run a **smoke test first**: confirm CPU inference works on aarch64 and record the time.
5. `calibrate_and_store` (`ml` queue): fit isotonic calibration on the backtest predictions, then write `ChaosPrediction` rows and a `ModelRun`.
6. **Stretch:** try `sdm.models.KumoRelational` with the races, drivers, circuits and lap-window tables linked directly, and compare it with the tabular version.

### Evaluation

- Leave one season out, 2018–2025.
- Compare Kumo, the Beta-Binomial baseline and a LightGBM reference on identical splits.
- Metrics: Brier score, log-loss, ROC-AUC, reliability curve (10 bins) and expected calibration error.
- Sanity check: Canada's historical safety-car race rate should come out near 60%, per McLaren.
- Use the Mendeley SC-labelled dataset (2022–2025) to cross-check the SC labels.
- Save everything to `ModelRun.metrics`.

### Endpoints

- `/api/chaos/races/<y>/<r>/`
- `/api/chaos/races/<y>/<r>/drivers/`
- `/api/chaos/races/<y>/<r>/laps/`
- `/api/chaos/circuits/<circuit_key>/history/`
- `/api/chaos/drivers/<code>/profile/`
- `/api/chaos/model/` (current run, metrics, calibration bins)

## Phase 3: Stewards assistant (new app `api/assistant/`)

**Corpus**

FIA Sporting and Technical Regulations (by year), stewards' decision documents and event notes. Fetch politely and store the original PDFs plus a `DocumentSource` row (URL, type, year, race, sha256).

**Ingestion** (`rag` queue)

1. Parse the PDF.
2. Chunk by section, at about 300–500 tokens, keeping article numbers.
3. Embed with `bge-small-en-v1.5` (384-d, CPU-friendly) or a hosted embedding API.
4. Store `DocChunk` rows with text, `vector(384)` (pgvector on Neon), a `tsvector`, page, section, article and source. Add an HNSW index.

**Retrieval**

Postgres full-text search and pgvector, each top-50, merged with reciprocal rank fusion, then reranked by `bge-reranker-v2-m3` to the top 8. Run the reranker in `worker-rag`, not in web.

**Agent (LangGraph)**

Tools that call Django services in-process:
- `search_documents(query, year?, doc_type?)`
- `get_incidents(y, r)`
- `get_track_status(y, r)`
- `get_chaos(y, r)`
- `similar_past_decisions(offence, n)`

The agent answers only from tool results, cites document, page and article, and says so when the evidence is missing.

**Endpoint:** `POST /api/assistant/ask` with body `{question, year?, round?}`. It streams tokens and citations over the existing SSE helper and is limited by `APIKeyThrottle` (assistant calls cost more).

**Evaluation**

About 100 hand-written questions with gold citations, covering rule lookups, penalty precedent and race-specific questions. Report recall@8, citation accuracy and answer correctness (LLM-judged plus spot checks), saved to `assistant/evals/`.

**MCP**

Using `mcp-builder`, expose read-only tools for race data, chaos and document search as an MCP server (`mcp/` service in compose). Start with plain tools. Switch to a Code Mode style single `run_code` tool over a typed client if the tool count passes about 15.

## Phase 4: Docs and launch

- README:
  - hero GIF;
  - Archify diagram generated from the codebase;
  - quick start (`docker compose up`);
  - endpoint table;
  - three example `curl` calls;
  - design decisions (caching tiers, nonblocking SSE, queue tiers);
  - performance numbers;
  - Chaos Point model card with calibration plot;
  - assistant eval results;
  - "where AI helped / what I rejected" section.
- Publish a Python client package (`pip install f1controlroom`) wrapping the public endpoints.

## Definition of done

- Every phase merged with green CI and no change to existing responses (snapshot tests).
- The VM runs everything under Docker within the memory budget.
- `ModelRun` metrics are public at `/api/chaos/model/`.
