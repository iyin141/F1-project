# F1 Project Architecture & Worker Memory Profile

This document provides a detailed overview of the backend architecture for the F1 Project, specifically focusing on the asynchronous worker tiers, their roles, and their memory consumption footprint.

## Core Architecture Overview

The F1 Project backend is built around a non-blocking, asynchronous architecture designed to handle heavy data extraction tasks (like downloading and parsing FastF1 telemetry) without locking up the API HTTP threads. 

### Key Components:
1. **Django/Waitress API (Frontend Gateway):** Handles incoming HTTP requests, validates API keys, and checks the PostgreSQL database cache.
2. **Celery Task Manager & Redis Pub/Sub:** If data is missing from the cache, the API enqueues a background task and immediately converts the HTTP response into a Server-Sent Events (SSE) stream.
3. **Celery Worker Tiers:** Dedicated, isolated process pools that execute tasks based on data payload size and duration.
4. **PostgreSQL Database:** Acts as the persistent cache where finalized parsed data is stored via bulk inserts.

---

## Worker Tiers & Memory Consumption

To ensure stability on the Oracle Cloud A1 Flex instance (4 OCPUs, 24GB RAM), workers are segmented into distinct "Tiers" based on their workload profiles.

### Tier 1: Instant Operations (`tier1_instant`)
- **Role:** Handles very fast, low-overhead endpoints (e.g., Standings, Schedules, Driver Career summaries). These usually involve simple API calls to Ergast/Jolpica.
- **Processes:** 8 concurrent processes.
- **Memory Footprint:** **~50MB - 100MB per process** (Lightweight).

### Tier 2: Fast Data Fetching (`tier2_fast`)
- **Role:** Handles endpoints that require moderate data aggregation, such as Race Results, Qualifying Results, Weather snapshots, and Pit Stop data.
- **Processes:** 8 concurrent processes.
- **Memory Footprint:** **~150MB - 250MB per process**. Uses small Pandas DataFrames.

### Tier 3: Medium Operations (`tier3_medium`)
- **Role:** Handles complex session calculations for all drivers, such as Pace Analysis, Stint tracking, Laps, Sectors, and Position change timelines.
- **Processes:** 8 concurrent processes.
- **Memory Footprint:** **~300MB - 500MB per process**. Loads full-session telemetry data into memory to calculate deltas and stint medians.

### Tier 4: Heavy Telemetry Data (`tier4_telemetry`)
- **Role:** The heaviest operations. Downloads high-frequency, raw FastF1 telemetry data (speed, rpm, throttle, gears) down to the microsecond for individual drivers or overlays.
- **Processes:** 8 concurrent processes.
- **Memory Footprint:** **~1GB - 1.5GB per process**. 
- **Notes:** High I/O and RAM usage. Caches large Parquet files from FastF1 under the hood. The timeout for these workers is explicitly raised to 180 seconds due to the volume of data parsing.

### Tier 6: Notifications & Auth Tracking (`tier6_notifications`)
- **Role:** Handles non-blocking email dispatches and asynchronous API Key usage tracking (rate limits, request counts). 
- **Processes:** 5 concurrent processes.
- **Memory Footprint:** **~50MB per process** (Network/IO Bound, extremely lightweight).

---

## Memory Allocation Summary
On a full production load across all 37 processes, the memory is distributed approximately as follows:
- **API Server (Waitress/Gunicorn):** ~500MB
- **Redis & PostgreSQL:** ~1.5GB
- **Tier 1 & Tier 6:** ~650MB
- **Tier 2:** ~1.6GB
- **Tier 3:** ~3.2GB
- **Tier 4 (Telemetry):** ~10GB
- **Total System RAM Usage:** **~17.5GB / 24GB** (Leaves a safe ~6.5GB buffer for OS and burst workloads).

## Concurrency and Scaling
By isolating memory-heavy Telemetry workers into their own tier, a large influx of telemetry requests cannot starve the server's RAM or block lightweight Standings requests. The queue manager enforces a deduplication lock (`SETNX`), meaning 100 users asking for the same telemetry data will only ever trigger *one* Tier 4 worker, drastically reducing memory bloat.
