# Pub/Sub Architecture & Optimization Guide

This document serves as a blueprint for the asynchronous, streaming data pipeline built for the F1-Project backend. It details the complete flow of data, the generic components we created, the challenges we encountered, and the architectural optimizations we implemented. 

Use this guide as a reference when building out future endpoints (e.g., telemetry, standings, drivers) to ensure they follow the same highly performant pattern.

---

## 1. Full Data Flow (The "Pub/Sub" Pipeline)

When a user requests data that isn't immediately available in the database, the system avoids blocking the HTTP thread by utilizing a Redis Pub/Sub pipeline combined with Server-Sent Events (SSE). 

Here is the exact step-by-step flow:

1. **Client Request**: The frontend makes an HTTP request to a session endpoint (e.g., `/api/results/2024/2/R/`).
2. **Authentication & Tier Validation (Step 0)**: The system intercepts the request to validate the API Key and verify the Subscription Tier (e.g., Tier 4 for Telemetry) immediately at the HTTP layer. If valid, it dispatches the usage tracking (incrementing counters, checking rate limits) asynchronously to a **Tier 6 Notifications** worker (`tier6_notifications`), ensuring that the authentication overhead does not block the API response.
3. **Cache Check (`repository.py`)**: The system checks the PostgreSQL database for the payload. If it exists, it returns it instantly.
4. **Task Enqueue (`nonblocking.py` & `manager.py`)**: 
   - If the data is missing, the API generates a unique `task_key` (e.g., `race_results:2024:2`).
   - The `TaskManager` attempts to acquire a Redis distributed lock for this `task_key`.
   - If the lock is acquired (meaning no one else is currently fetching this data), it creates a `TaskRecord` in the DB and enqueues a Celery task.
5. **Subscription (`streaming.py`)**: The API view transitions into a `StreamingHttpResponse`. It subscribes to the Redis Pub/Sub channel matching the `task_key` (e.g., `task_result:race_results:2024:2`) and yields a "loading" message to the frontend, keeping the connection open.
6. **Worker Execution (`populate_race_results.py`)**: 
   - The Celery worker picks up the task, downloads the raw data via FastF1, and parses it.
   - It serializes the data into standard JSON.
7. **Publishing (`worker_utils.py`)**:
   - Before doing heavy database writes, the worker calls `worker_utils.handle_result()`.
   - This function immediately publishes the finalized JSON payload to the Redis Pub/Sub channel.
8. **Client Delivery**: The waiting Django API view intercepts the published Redis message and streams the final JSON to the frontend, automatically closing the HTTP connection.
9. **Asynchronous DB Save (`store.py`)**: With the user already served, the Celery worker performs heavy database inserts in the background, caching the data for the next user.

---

## 2. Generic Reusable Components

When porting this architecture to other endpoints, leverage these generic classes and utilities:

### `TaskManager` (`api/queue/manager.py`)
Responsible for ensuring a single task is only queued once. Use `TaskManager.enqueue_if_needed(task_key, celery_task_function, *args)`. It handles Redis locking and `TaskRecord` creation automatically.

### `NonBlocking` Service (`api/services/nonblocking.py`)
Acts as the bridge between views and the `TaskManager`. Use it to generate standard caching keys and enqueue tasks without writing boilerplate database checks in your views.

### Streaming Listeners (`api/services/streaming.py`)
Use `json_stream(task_key)` for single endpoints and `combined_json(task_keys)` when a view needs to wait for multiple workers to finish (e.g., waiting for both Race and Qualifying results). It handles Redis subscription and timeouts.

### `worker_utils.handle_result` (`api/services/worker_utils.py`)
The mandatory exit-point for all Celery workers. You must pass your finalized data to this function. It automatically:
1. Publishes the result to the Redis PubSub stream.
2. Backfills the standard Redis cache (`cache.set()`).

---

## 3. Problems Faced & Solutions Implemented

### Problem A: Stream Timeouts & Queue Blocking (The DB Bottleneck)
**Issue:** The frontend streaming connection was timing out after 54 seconds (`combined_json.timeout`). Logs revealed that while the FastF1 data was fetched in ~10 seconds, the Celery worker took 70+ seconds to save the data to PostgreSQL. Because the worker used a sequential `update_or_create` loop for all 20 drivers, the worker threads were locked up, preventing subsequent queued tasks from running. By the time the next task started, the frontend had timed out.
**Solution:** We replaced the sequential database loop with a **Memory-Buffered Bulk Insert**. We built `bulk_store_driver_lap_analysis` which normalizes all 20 drivers in memory, fetches existing records with a single `in_bulk()` query, and executes exactly two database calls: `bulk_create` and `bulk_update`. 
**Result:** DB save times dropped from 70 seconds to ~2 seconds, entirely eliminating worker bottlenecks and stream timeouts.

### Problem B: Practice Session Parsing Crashes
**Issue:** Workers attempting to seed Practice sessions (`FP1`, `FP2`, `FP3`) were crashing with a `KeyError: 'driver_code'`. 
**Solution:** The FastF1 parsed payload shape drifted from what the `PracticeResultSerializer` expected. We updated the parser to accurately extract `lap_time`, `lap_number`, and mapped the `Abbreviation` column to `driver_code`, syncing the two contracts perfectly.

### Problem C: Silent Cache Backfill Failures
**Issue:** The Redis standard cache was not being populated after a worker successfully fetched data. Repeated requests forced the API to re-query the PostgreSQL database.
**Solution:** The `ttl_for` cache utility required a `year` parameter to determine expiration logic, but `handle_result` wasn't passing it, silently suppressing the cache save. We updated the `handle_result` signature to accept and parse the `year`, restoring instant 10ms cache hits for repeat requests.

### Problem D: Messy Seeding Operations Crashing the Server
**Issue:** Sending massive arrays of concurrent tasks to seed an entire historical season was overwhelming the Redis locks and locking up the database pool.
**Solution:** We built an **Iterative Coordinator Script** (`seed_races.py`). Instead of a shotgun approach, the script dispatches tasks for exactly *one race weekend*, polls the DB until they complete, logs the progress to a file, and then safely moves to the next weekend. This completely decoupled seeding from the API server limits.

---

> [!TIP]
> **Future Development Rule:** Never perform heavy database insertions *before* publishing to the Redis stream. Always yield data to the user as fast as possible, and offload database serialization to the background or use `bulk_create` to minimize thread-locking.
