# F1 Project Architecture & Worker Tiers

## Overview
The F1 Project backend is an event-driven, microservices-oriented monolithic Django application. It relies heavily on asynchronous Celery workers, Redis for caching/pub-sub, and PostgreSQL for persistent JSONB storage.

The system uses a Non-Blocking API architecture where endpoints instantly return `202 Accepted` and offload data fetching, parsing, and caching to Celery workers. The workers publish their results via Redis Pub/Sub, and clients subscribe to SSE streams to receive the final payload.

## Core Components
1. **Django Web Server**: Handles incoming HTTP requests, enforces API structure using Django Rest Framework, and returns cached data or enqueues asynchronous tasks.
2. **PostgreSQL**: Stores large JSONB payloads representing driver telemetry, race results, lap analysis, and track statuses.
3. **Redis**: Serves as the Celery broker, Pub/Sub message bus, and caching layer.
4. **Celery Workers**: Categorized into multiple tiers to prevent memory exhaustion and handle the computationally heavy FastF1 data parsing.

---

## Worker Tiers & Memory Profiles

The system's data extraction relies on `FastF1`, which uses Pandas DataFrames under the hood. Telemetry processing can cause significant memory spikes. To prevent OOM (Out Of Memory) errors, the workers are strictly tiered.

### 1. `tier1_core`
- **Role**: Handles critical orchestration tasks, fast synchronous DB writes, and internal system maintenance.
- **Memory Profile**: Very Low (~100-200MB)
- **Concurrency**: High (e.g., `--concurrency=4` or `--pool=threads`)
- **Key Tasks**: Backfill detection, orchestrating data dependencies.

### 2. `tier2_fast`
- **Role**: Extracts basic structured data from the Jolpica API and lightweight FastF1 APIs.
- **Data Types**: Race results, qualifying results, schedule, standings, weather.
- **Memory Profile**: Low (~200-400MB)
- **Concurrency**: Medium (`--concurrency=3`)
- **Key Tasks**: `populate_race_results`, `populate_weather_data`, `populate_pit_stop_data`.

### 3. `tier3_medium`
- **Role**: Parses moderate-to-heavy FastF1 data like lap-by-lap pace, stint analysis, tyre strategies, and sector timings. Requires instantiating Pandas DataFrames but does not process 10Hz telemetry.
- **Memory Profile**: Moderate (~500MB - 1GB)
- **Concurrency**: Low (`--concurrency=2`)
- **Key Tasks**: `populate_laps`, `populate_tyre_strategy`, `populate_stint_analysis`.

### 4. `tier4_telemetry`
- **Role**: The heaviest worker queue. Dedicated entirely to extracting, merging, and normalizing high-frequency (10Hz) driver telemetry across an entire session.
- **Memory Profile**: Extremely High (up to 2GB - 3GB per process)
- **Concurrency**: Strictly `1` (`--concurrency=1`)
- **Key Tasks**: `populate_session_telemetry`, `populate_telemetry` (driver-specific).
- **Notes**: Processing full session telemetry involves downloading hundreds of megabytes of raw CSVs, aligning timestamps, and aggregating spatial points. This tier must run in isolation to prevent crashing other queues.

---

## The Non-Blocking Pub/Sub Flow

1. **Client Request**: Client calls an endpoint (e.g., `/api/session/laps/`).
2. **Cache/DB Check**: The system checks Redis. If missing, it checks PostgreSQL.
3. **Task Dispatch**: If the data doesn't exist, a Celery task is enqueued to the appropriate tier. The server returns `{ "status": "processing", "task_key": "..." }`.
4. **SSE Subscription**: The client connects to `/api/stream/task/<task_key>/` to listen for updates.
5. **Worker Execution**: The Celery worker fetches the data, stores it in the DB, caches it in Redis, and finally publishes the payload to the Redis Pub/Sub channel matching the `task_key`.
6. **Payload Delivery**: The Django server streams the published payload back to the waiting client.
