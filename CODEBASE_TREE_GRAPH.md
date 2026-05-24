# Codebase Tree & Diagrams — backend/api

Last updated: 2026-05-23

This document provides per-endpoint tree diagrams and concise file descriptions for the `backend/api` codebase. Each file reference is linked to the workspace-relative path so you can jump to sources quickly.

Notes:

- Trees are grouped by logical domain: Drivers, Results/Races, Constructors, Analysis, Unified, Schedule, Background Tasks & Queue, Models, Services, Management Commands, Common utilities, Middleware, Tests, Migrations, Templates.
- Diagrams use Mermaid for quick visualization of how endpoints, services, models and background tasks connect.

---

**Overview (mermaid)**

```mermaid
flowchart LR
  subgraph API[API Endpoints]
    DriversAPI[Drivers API\n(api/drivers/*)]
    ResultsAPI[Results API\n(api/results/*)]
    ConstructorsAPI[Constructors API\n(api/constructors/*)]
    UnifiedAPI[Unified Endpoints\n(api/services/unified_service.py / api/views.py)]
    ScheduleAPI[Schedule API\n(api/schedule/*)]
  end

  subgraph Services[Service Layer]
    DriversSvc[Drivers Services\n(api/drivers/services/*)]
    ResultsSvc[Results Services\n(api/results/services/*)]
    ConstructSvc[Constructors Services\n(api/constructors/services.py)]
    UnifiedSvc[Unified Service\n(api/services/unified_service.py)]
    AnalysisSvc[Analysis Service\n(api/services/analysis.py)]
  end

  subgraph Models[Persistence]
    F1Driver[Drivers Model\n(api/models/drivers.py)]
    RacesModel[Races & Results\n(api/models/races.py)]
    StandingsModel[Standings\n(api/models/standings.py)]
    AnalysisModel[Analysis\n(api/models/analysis.py)]
    UnifiedModel[SessionData\n(api/models/unified.py)]
  end

  subgraph Tasks[Background & Queue]
    QueueMgr[TaskManager\n(api/queue/manager.py)]
    CeleryTasks[Celery Tasks\n(api/tasks.py)]
    Seeding[Seeding & Backfill\n(api/services/seeding.py)]
  end

  DriversAPI -->|calls| DriversSvc
  ResultsAPI -->|calls| ResultsSvc
  ConstructorsAPI -->|calls| ConstructSvc
  UnifiedAPI -->|calls| UnifiedSvc
  ScheduleAPI -->|calls| api/schedule/services.py

  DriversSvc --> F1Driver
  ResultsSvc --> RacesModel
  ResultsSvc --> StandingsModel
  AnalysisSvc --> AnalysisModel
  UnifiedSvc --> UnifiedModel

  DriversSvc -->|enqueue| QueueMgr
  ResultsSvc -->|enqueue| QueueMgr
  QueueMgr --> CeleryTasks
  CeleryTasks -->|writes| F1Driver
  CeleryTasks -->|writes| RacesModel
  CeleryTasks -->|writes| StandingsModel
  Seeding -->|uses| CeleryTasks
```

---

## Drivers (api/drivers)

- `api/drivers/`
  - [api/drivers/**init**.py](api/drivers/__init__.py): package init.
  - [api/drivers/views.py](api/drivers/views.py): HTTP views for drivers endpoints (standings, career, season, search, sync). Implements DB-first flows and enqueues background tasks where needed.
  - [api/drivers/urls.py](api/drivers/urls.py): URL routing for driver endpoints.
  - [api/drivers/serializers.py](api/drivers/serializers.py): DRF serializers for driver responses (career, season, standings payloads).
  - [api/drivers/repository.py](api/drivers/repository.py): Low-level data access abstraction for driver records and lookups.
  - [api/drivers/jolpica_client.py](api/drivers/jolpica_client.py): External Jolpica/Ergast HTTP client for driver-related endpoints.
  - [api/drivers/fake_jolpica.py](api/drivers/fake_jolpica.py): Test/deterministic Jolpica stub used in unit/integration tests.
  - `api/drivers/services/` (package)
    - [api/drivers/services/**init**.py](api/drivers/services/__init__.py)
    - [api/drivers/services/sync_service.py](api/drivers/services/sync_service.py): DriverSyncService — DB-first sync, Jolpica fallback, idempotent upsert, `sync_season_drivers` and `sync_all_seasons` (created during Phase 1-3).
    - [api/drivers/services/standings.py](api/drivers/services/standings.py): Builds driver standings payloads and readiness meta.
    - [api/drivers/services/season.py](api/drivers/services/season.py): Driver season breakdown logic.
    - [api/drivers/services/career.py](api/drivers/services/career.py): Driver career aggregation service.

Connections:

- `api/drivers/views.py` calls services in `api/drivers/services/*`, which read/write `api/models/drivers.py` and may enqueue Celery tasks via `api/queue/manager.py` (e.g., `populate_driver_career`, `sync_drivers_task`).

---

## Results / Races (api/results)

- `api/results/`
  - [api/results/**init**.py](api/results/__init__.py): package init.
  - [api/results/views.py](api/results/views.py): Race/qualifying results endpoints — uses non-blocking pattern (cache → DB → enqueue) to avoid blocking Jolpica calls.
  - [api/results/urls.py](api/results/urls.py): Results routing.
  - [api/results/serializers.py](api/results/serializers.py): Serializers for race/qualifying/sprint results payloads.
  - [api/results/repository.py](api/results/repository.py): Data access & translation layer for result rows / payloads.
  - [api/results/helpers.py](api/results/helpers.py): Utility helpers used by results services and views.
  - `api/results/services/`
    - [api/results/services/weekend.py](api/results/services/weekend.py): Aggregates weekend-level data (results, sessions) into a single payload.
    - [api/results/services/race.py](api/results/services/race.py): Race session data extraction and formatting.
    - [api/results/services/practice.py](api/results/services/practice.py): Practice session handling.
    - [api/results/services/qualifying.py](api/results/services/qualifying.py): Qualifying results processing.
    - [api/results/services/sprint.py](api/results/services/sprint.py): Sprint and sprint-shootout handling.

Connections:

- Results services frequently enqueue Celery tasks (e.g., `populate_race_results`, `populate_session_data`) via `api/queue/manager.py` and rely on `api/services/nonblocking.py` for the 4-step response pattern.

---

## Constructors (api/constructors)

- `api/constructors/`
  - [api/constructors/**init**.py](api/constructors/__init__.py)
  - [api/constructors/views.py](api/constructors/views.py): Endpoints for constructors standings and related data.
  - [api/constructors/urls.py](api/constructors/urls.py): Routing for constructors.
  - [api/constructors/services.py](api/constructors/services.py): Business logic to build constructor standings, season data, and readiness.
  - [api/constructors/serializers.py](api/constructors/serializers.py): Response serializers for constructors payloads.
  - [api/constructors/repository.py](api/constructors/repository.py): Data access layer for constructor rows.
  - [api/constructors/jolpica_client.py](api/constructors/jolpica_client.py): External Jolpica client focused on constructor endpoints.

Connections:

- Constructors endpoints follow similar cache/DB/task flows as Drivers and Results, using `api/queue/manager.py` for background persistence tasks.

---

## Analysis (Telemetry / Analysis)

- Models & Services
  - [api/models/analysis.py](api/models/analysis.py): Models storing telemetry and analysis payloads (DriverLapAnalysis, DriverTelemetry, etc.).
  - [api/services/analysis.py](api/services/analysis.py): Analysis pipelines and helpers to compute lap-by-lap analysis, telemetry overlays, and derived metrics.
  - [api/services/telemetry_cache.py](api/services/telemetry_cache.py): Telemetry caching helpers used to store/retrieve large telemetry traces.

- Views & Endpoints
  - Analysis-related endpoints are wired into the top-level `api/views.py` and specific `api/results/views.py` where telemetry and analysis endpoints are exposed.

Connections:

- Analysis services often require heavy CPU/IO; they are run or seeded via Celery tasks (e.g., `populate_telemetry` in `api/tasks.py`) which persist results into models in `api/models/analysis.py` and backfill Redis via `api/services/cache_service.py`.

---

## Unified (session-level aggregated data)

- [api/models/unified.py](api/models/unified.py): `SessionData` model, canonical persisted payload for session-level aggregated data.
- [api/services/unified_service.py](api/services/unified_service.py): Primary service that composes session-level unified payloads (weather, incidents, pit stops, telemetry summary, positions, DRS, track status) and implements caching/readiness.
- [api/views.py](api/views.py): Hosts several unified endpoints (Module S non-blocking pattern applied here).

Connections:

- `unified_service.py` aggregates data from `api/results/services/*`, `api/services/analysis.py`, and may enqueue background backfill/prefetch tasks using `api/queue/manager.py`.

---

## Schedule (api/schedule)

- `api/schedule/`
  - [api/schedule/**init**.py](api/schedule/__init__.py)
  - [api/schedule/views.py](api/schedule/views.py): Schedule endpoints (season calendar, upcoming races).
  - [api/schedule/urls.py](api/schedule/urls.py)
  - [api/schedule/services.py](api/schedule/services.py): Schedule retrieval and formatting logic.
  - [api/schedule/serializers.py](api/schedule/serializers.py)
  - [api/schedule/repository.py](api/schedule/repository.py): Data access for season schedules.
  - [api/schedule/fastf1_client.py](api/schedule/fastf1_client.py): Client to fetch schedule-related data from FastF1 or Jolpica.

Connections:

- Beat tasks (see `api/tasks.py` → `check_for_completed_sessions`) use Schedule data to trigger prefetch/prefill tasks.

---

## Background Tasks & Queue

- `api/queue/`
  - [api/queue/**init**.py](api/queue/__init__.py)
  - [api/queue/manager.py](api/queue/manager.py): TaskManager — deduplication, enqueue_if_needed, get_by_key, mark_running/complete/failed. Central to non-blocking design.

- `api/tasks.py` (Celery)
  - [api/tasks.py](api/tasks.py): All Celery task definitions (`populate_race_results`, `populate_session_data`, `populate_standings`, `populate_driver_career`, `sync_drivers_task`, `sync_all_drivers_task`, prefetch/seed/beat tasks, email tasks). Tasks call management command `run()` functions or services directly and mark status via TaskManager.

- `api/services/`
  - [api/services/task_manager.py](api/services/task_manager.py): Service wrapper to interact with task persistence records (TaskRecord model and TaskManager patterns).
  - [api/services/seeding.py](api/services/seeding.py): Seeding & historical backfill logic (calls TaskManager.enqueue_if_needed to dispatch `seed_historical_round` etc.).
  - [api/services/pagination_cache.py](api/services/pagination_cache.py): Helpers used by background pagination tasks.

- Cache & Load-locks
  - [api/services/cache_service.py](api/services/cache_service.py): Read-through / write-through cache helpers (Redis) and load-lock keys (SETNX) plus task-status keys. Used by `nonblocking.py`.
  - [api/services/nonblocking.py](api/services/nonblocking.py): Implements Module S 4-step non-blocking pattern used across many views.

Connections diagram (mermaid):

```mermaid
flowchart TD
  API_VIEWS[API Views (non-blocking)] -->|check cache| CacheService[api/services/cache_service.py]
  API_VIEWS -->|DB fallback| Models[api/models/*]
  API_VIEWS -->|enqueue| QueueMgr[api/queue/manager.py]
  QueueMgr -->|launch| Celery[api/tasks.py]
  Celery -->|call| ManagementCmds[api/management/commands/*]
  Celery -->|persist| Models
  Celery -->|backfill| CacheService
```

---

## Models (api/models)

- `api/models/__init__.py` — model exports for Django discovery.
- [api/models/drivers.py](api/models/drivers.py): `F1Driver` model (driver_id, code, number, given_name, family_name, nationality, dob, seasons JSONField). Primary cache for driver info.
- [api/models/races.py](api/models/races.py): Race schedule and result persistence models (SeasonSchedule, RaceResultData, QualifyingResultData, PracticeResultData).
- [api/models/standings.py](api/models/standings.py): Driver/Constructor standings and summaries.
- [api/models/unified.py](api/models/unified.py): `SessionData` persisted unified payloads.
- [api/models/queue.py](api/models/queue.py): TaskRecord model for tracking background tasks.
- [api/models/auth.py](api/models/auth.py): APIKey model & auth persistence.
- [api/models/analysis.py](api/models/analysis.py): Telemetry + analysis models (DriverLapAnalysis, DriverTelemetry).

Notes:

- Migrations for model changes live in `api/migrations/` (including `0018_f1driver.py` added for `F1Driver`).

---

## Services (api/services)

Top-level services used by endpoints and tasks (quick list):

- [api/services/unified_service.py](api/services/unified_service.py): Constructs unified session payloads.
- [api/services/results.py](api/services/results.py): Higher-level orchestration for race/qualifying results.
- [api/services/drivers.py](api/services/drivers.py): Driver-related helpers and small wrappers.
- [api/drivers/services/sync_service.py](api/drivers/services/sync_service.py): DriverSyncService (detailed earlier).
- [api/services/analysis.py](api/services/analysis.py): Analysis & telemetry processing.
- [api/services/cache_service.py](api/services/cache_service.py): Redis read/write/load-locks/task-status functions.
- [api/services/seeding.py](api/services/seeding.py): Historical seeding/backfill orchestration.
- [api/services/schedule.py](api/services/schedule.py): Schedule-specific helpers.
- [api/services/persistence.py](api/services/persistence.py): Persistence layer helpers used by multiple services.
- [api/services/extraction.py](api/services/extraction.py): Extraction/transform helpers for raw source responses.
- [api/services/driver_career_service.py](api/services/driver_career_service.py): Legacy-compatible career aggregator used by `api/drivers/views.py`.

---

## Management Commands (api/management/commands)

These are entry points often invoked by Celery tasks or run manually for seeding:

- [api/management/commands/populate_race.py](api/management/commands/populate_race.py): Seed race results and session-level data.
- [api/management/commands/populate_standings.py](api/management/commands/populate_standings.py): Build and persist season standings.
- [api/management/commands/populate_telemetry.py](api/management/commands/populate_telemetry.py): Fetch and persist telemetry traces.
- [api/management/commands/populate_session.py](api/management/commands/populate_session.py): Seed session-level unified payloads.
- [api/management/commands/populate_driver_career.py](api/management/commands/populate_driver_career.py): Populate driver career aggregates.
- [api/management/commands/sync_drivers.py](api/management/commands/sync_drivers.py): One-off or ranged driver sync CLI (invokes DriverSyncService). (Created earlier)
- [api/management/commands/seed_historical_data.py](api/management/commands/seed_historical_data.py): Bulk historical seed orchestration (dispatches `seed_historical_round` tasks).
- [api/management/commands/create_internal_key.py](api/management/commands/create_internal_key.py): Admin convenience script to create internal API keys.

Connections:

- Celery tasks call these commands internally (e.g., `from api.management.commands.populate_race import run`) to reuse the same logic for both CLI and background runs.

---

## Common & Utilities (api/common)

- [api/common/utils.py](api/common/utils.py): Small helpers used across domains (e.g., `is_current_year`).
- [api/common/serializers.py](api/common/serializers.py): Shared DRF serializers (Readiness, etc.).
- [api/common/response.py](api/common/response.py): Standardized error payload builder.
- [api/common/readiness.py](api/common/readiness.py): Readiness metadata builder used by many endpoints.
- [api/common/request_id.py](api/common/request_id.py): Request ID plumbing middleware helper.
- [api/common/pagination.py](api/common/pagination.py): Pagination helpers.
- [api/common/mixins.py](api/common/mixins.py): Shared view mixins.
- [api/common/constants.py](api/common/constants.py): Global constants used throughout the API.

---

## Queue / Task Tracking (persistence)

- [api/models/queue.py](api/models/queue.py): `TaskRecord` model storing task_key ↔ task_id, status and timestamps.
- [api/services/task_manager.py](api/services/task_manager.py): High-level helpers interacting with TaskRecord rows.
- [api/queue/manager.py](api/queue/manager.py): TaskManager implementation for enqueueing, deduping, marking states; used by `nonblocking.py` and views.
- [api/views/task_status.py](api/views/task_status.py): Endpoint(s) to poll background task status for clients.

---

## Middleware, Throttling, Session

- [api/middleware/no_cache.py](api/middleware/no_cache.py): No-cache response middleware.
- [api/middleware/csrf_exempt.py](api/middleware/csrf_exempt.py): CSRF exempt helper.
- [api/throttling.py](api/throttling.py): Request throttling policies.
- `api/session/` (runtime/session helpers)
  - [api/session/runtime.py](api/session/runtime.py): Session runtime objects & helpers for in-process session caching.
  - [api/session/fake_fastf1.py](api/session/fake_fastf1.py): FastF1 test harness used by local integration tests.

---

## Tests

- `api/tests/unit/` — unit tests for utilities, endpoints, services (e.g., `test_driver_endpoints.py`, `test_api_endpoints.py`, `test_unified_service.py`).
- `api/tests/integration/` — integration tests that target live services (e.g., `test_live_services.py`).

---

## Migrations

- `api/migrations/` contains the migration history. Of note:
  - `api/migrations/0018_f1driver.py` — migration that creates `api_f1driver` table for the new `F1Driver` model.
  - earlier migrations handle telemetry, taskrecord changes, and other schema updates.

---

## Templates

- [api/templates/api/schedule.html](api/templates/api/schedule.html): Small HTML view used by schedule endpoints (debug/UI).

---

## Quick Cross-References / How data flows for a typical request

1. Client hits `/api/drivers/search/?q=Verstappen` → `api/drivers/views.py`
2. View calls `DriverSyncService.search_drivers()` or `api/drivers/repository.py` → checks `api/models/drivers.py` (DB)
3. If DB empty/miss → fallback to Jolpica (`api/drivers/jolpica_client.py`) and optionally enqueue `sync_drivers_task` via `api/queue/manager.py`.
4. If a longer background load is needed, view returns `202 Accepted` with `task_id` and the client polls `api/views/task_status.py`.
5. Celery worker (`api/tasks.py`) runs the queued task, calls management command or service, persists data to models, and backfills Redis via `api/services/cache_service.py`.

---

## Next Steps / Maintenance Tips

- Keep `api/services/nonblocking.py` and `api/services/cache_service.py` aligned: keys, TTLs, and load-lock logic are critical for correctness.
- When adding new long-running loads, prefer adding a Celery task in `api/tasks.py` and use `TaskManager.enqueue_if_needed` for dedup.
- Update this document when new endpoints, management commands, or task flows are added.

---

If you'd like, I can:

- Generate a condensed printable PDF of this document.
- Add inline diagrams per section (one mermaid diagram per endpoint) for deeper visual mapping.
- Create a navigable index file with direct links to the most-critical flows (e.g., non-blocking pattern files + tasks).

Would you like a more detailed mermaid diagram for one of the domains (Drivers, Results, or Telemetry)?
