#!/bin/bash
# start_prod.sh — Production startup for Oracle Cloud A1 Flex (4 OCPUs, 24GB RAM)
# Optimized for SSE + Redis pub/sub architecture
# Place this file in the backend/ directory alongside manage.py
# Run: chmod +x start_prod.sh && ./start_prod.sh

echo "Starting F1 API production environment (SSE + Pub/Sub optimized)..."
echo ""

# ---------------------------------------------------------------------------
# Uvicorn (ASGI) — Optimized for SSE streaming
# ---------------------------------------------------------------------------
# ASGI is required for non-blocking SSE streaming in Django.
# 2 Uvicorn workers, trimmed down from the 4 OCPUs of the Oracle VM to save RAM.
# Note: Uvicorn doesn't have a daemon mode built-in like Gunicorn, so we 
# run it in the background using nohup and &.
# ---------------------------------------------------------------------------
nohup uvicorn f1_project.asgi:application \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --log-level info > logs/uvicorn.log 2>&1 &

echo "Uvicorn started (2 async workers)."

# ---------------------------------------------------------------------------
# Celery workers — Optimized for pub/sub (no polling overhead)
# ---------------------------------------------------------------------------
# MEMORY PROFILE (current, post-trim):
#   - tier1_instant:      4 processes × ~75MB    = ~300MB
#   - tier2_fast:         4 processes × ~200MB   = ~800MB
#   - tier3_medium:       4 processes × ~125MB   = ~500MB  ← capped via --max-memory-per-child
#   - tier4_telemetry:    3 processes × ~366MB   = ~1.1GB  ← capped via --max-memory-per-child
#   - tier6_notifications:2 processes × ~50MB    = ~100MB
#
# RAM ALLOCATION SUMMARY (current, post-trim, on-VM only):
#   - API (Uvicorn):      ~250MB
#   - Redis:              ~1.5GB  ← set on server in /etc/redis/redis.conf (not this file)
#   - PostgreSQL:         N/A — Neon is a managed external DB, not running on this VM
#   - Tier 1 + 6:         ~400MB
#   - Tier 2:             ~800MB
#   - Tier 3:             ~500MB
#   - Tier 4 (telemetry): ~1.1GB
#   ─────────────────────────────
#   Total:                ~4.55GB / 24GB  (~19.45GB buffer)
#
# CHANGES FROM PREVIOUS ("revised") MODEL:
#   - Uvicorn:          4 → 2 workers
#   - tier1_instant:    8 → 4 processes
#   - tier2_fast:       8 → 4 processes
#   - tier3_medium:     8 → 4 processes, now capped ~125MB/worker (~3.2GB → ~500MB)
#   - tier4_telemetry:  6 → 3 processes, cap raised 100MB → ~366MB/worker (~6GB nominal → ~1.1GB actual cap)
#   - tier6_notifications: 5 → 2 processes
#   - Redis:            3GB → 1.5GB (applied on server, not here)
#
# NEW TOTAL: 19 processes (2 Uvicorn + 17 Celery incl. beat/flower)
# ---------------------------------------------------------------------------

# Tier 1 (instant): High priority, quick responses — standings, schedules, driver career
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier1_instant -n worker_tier1@%h --detach \
    --logfile=logs/celery_tier1.log

# Tier 2 (fast): Most common tasks — race results, qualifying, weather, pit stops
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier2_fast -n worker_tier2@%h --detach \
    --logfile=logs/celery_tier2.log

# Tier 3 (medium): Complex session calculations — pace analysis, stints, sectors
# --max-memory-per-child=125000 caps each process at ~125MB, holding the tier to ~500MB total
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier3_medium -n worker_tier3@%h --detach \
    --logfile=logs/celery_tier3.log \
    --max-memory-per-child=125000

# Tier 4 (telemetry): Heavy FastF1 downloads — raw telemetry, speed/rpm/throttle
# --max-memory-per-child=366000 caps each process at ~366MB and recycles on breach,
# holding the tier to ~1.1GB total across 3 workers
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=3 -Q tier4_telemetry -n worker_tier4@%h --detach \
    --logfile=logs/celery_tier4.log \
    --max-memory-per-child=366000

# Tier 6 (notifications): Email dispatch + async API key usage tracking
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=2 -Q tier6_notifications -n worker_tier6@%h --detach \
    --logfile=logs/celery_tier6.log

echo "Celery workers started (17 total concurrent processes, incl. beat/flower)."
echo "  - tier1_instant:       4 processes  ~300MB"
echo "  - tier2_fast:          4 processes  ~800MB"
echo "  - tier3_medium:        4 processes  ~500MB  (capped 125MB/worker)"
echo "  - tier4_telemetry:     3 processes  ~1.1GB  (capped 366MB/worker)"
echo "  - tier6_notifications: 2 processes  ~100MB"

# ---------------------------------------------------------------------------
# Celery beat — Scheduler (unchanged)
# ---------------------------------------------------------------------------
celery -A f1_project beat --loglevel=info --detach \
    --logfile=logs/celery_beat.log

echo "Celery beat started."

# ---------------------------------------------------------------------------
# Flower — Monitoring UI on port 5555 (unchanged)
# ---------------------------------------------------------------------------
celery -A f1_project flower --port=5555 --detach \
    --logfile=logs/flower.log

echo "Flower started at http://localhost:5555"

echo ""
echo "============================================================"
echo "All services started. Production configuration:"
echo ""
echo "  HTTP Server (Uvicorn ASGI):"
echo "    - Processes: 2"
echo "    - Using asyncio event loops (thousands of connections/process)"
echo "  Workers (Celery):"
echo "    - Total processes: 17 (incl. beat + flower)"
echo "    - Using prefork (process isolation for CPU-bound work)"
echo "    - Tier 3 capped at 125MB/worker, Tier 4 at 366MB/worker via --max-memory-per-child"
echo ""
echo "  Redis:"
echo "    - maxmemory: 1.5gb (set on server in /etc/redis/redis.conf, not this script)"
echo "    - maxmemory-policy: allkeys-lru"
echo "    - Ensure maxclients >= 100 (check: redis-cli CONFIG GET maxclients)"
echo "    - Django cache: 1 pool (config in settings.py)"
echo "    - Pub/sub service: Dedicated connection (pubsub.py)"
echo ""
echo "  RAM Allocation (current, post-trim, on-VM only):"
echo "    - API + Redis:       ~1.75GB  (Neon Postgres is external, not counted here)"
echo "    - Tier 1 + 6:        ~400MB"
echo "    - Tier 2:            ~800MB"
echo "    - Tier 3:            ~500MB"
echo "    - Tier 4 telemetry:  ~1.1GB"
echo "    - Total:             ~4.55GB / 24GB (~19.45GB buffer)"
echo ""
echo "  Streaming (SSE + Pub/Sub):"
echo "    - No polling overhead (180-second stream timeout)"
echo "    - Workers publish once, all subscribers notified instantly"
echo "    - Deduplication: multiple requests for same task = one worker task"
echo ""
echo "============================================================"
echo ""
echo "Logs location: backend/logs/"
echo "To stop all services: pkill -f uvicorn && pkill -f celery && pkill -f flower"
echo "To check Redis memory: redis-cli INFO memory | grep used_memory_human"
echo "To check Redis connections: redis-cli INFO stats | grep connected_clients"
echo ""