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
# 4 Uvicorn workers are perfectly matched to the 4 OCPUs of the Oracle VM.
# Note: Uvicorn doesn't have a daemon mode built-in like Gunicorn, so we 
# run it in the background using nohup and &.
# ---------------------------------------------------------------------------
nohup uvicorn f1_project.asgi:application \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 4 \
    --log-level info > logs/uvicorn.log 2>&1 &

echo "Uvicorn started (4 async workers)."

# ---------------------------------------------------------------------------
# Celery workers — Optimized for pub/sub (no polling overhead)
# ---------------------------------------------------------------------------
# MEMORY PROFILE (revised):
#   - tier1_instant:      8 processes × ~75MB   = ~600MB
#   - tier2_fast:         8 processes × ~200MB  = ~1.6GB
#   - tier3_medium:       8 processes × ~400MB  = ~3.2GB
#   - tier4_telemetry:    6 processes × ~1GB    = ~6GB   ← capped via worker_max_memory_per_child
#   - tier6_notifications:5 processes × ~50MB   = ~250MB
#
# RAM ALLOCATION SUMMARY (revised):
#   - API (Gunicorn):     ~500MB
#   - Redis:              ~3GB    ← provisioned in /etc/redis/redis.conf
#   - PostgreSQL (Neon):  ~1GB
#   - Tier 1 + 6:         ~850MB
#   - Tier 2:             ~1.6GB
#   - Tier 3:             ~3.2GB
#   - Tier 4 (telemetry): ~6GB
#   ─────────────────────────────
#   Total:                ~16.15GB / 24GB  (~7.85GB buffer)
#
# BENEFIT OF PUB/SUB:
#   - Workers publish once → all subscribers notified instantly
#   - No status key updates (old polling model had many SET operations)
#   - Freed CPU allows modest concurrency increases
#
# CHANGES FROM OLD MODEL:
#   - tier1_instant:   6 → 8 processes
#   - tier2_fast:      6 → 8 processes
#   - tier3_medium:    6 → 8 processes
#   - tier4_telemetry: 4 → 6 processes, capped at 1GB each (was 1.25GB)
#   - tier5_pagination: Removed (8 processes freed)
#   - backfill:        Removed (2 processes freed)
#   - tier6_notifications: 4 → 5 processes
#   - Redis:           ~500MB → 3GB (maxmemory 3gb in redis.conf)
#
# NEW TOTAL: 35 processes
# ---------------------------------------------------------------------------

# Tier 1 (instant): High priority, quick responses — standings, schedules, driver career
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier1_instant -n worker_tier1@%h --detach \
    --logfile=logs/celery_tier1.log

# Tier 2 (fast): Most common tasks — race results, qualifying, weather, pit stops
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier2_fast -n worker_tier2@%h --detach \
    --logfile=logs/celery_tier2.log

# Tier 3 (medium): Complex session calculations — pace analysis, stints, sectors
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier3_medium -n worker_tier3@%h --detach \
    --logfile=logs/celery_tier3.log

# Tier 4 (telemetry): Heavy FastF1 downloads — raw telemetry, speed/rpm/throttle
# worker_max_memory_per_child=1000000 caps each process at ~1GB and recycles on breach
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier4_telemetry -n worker_tier4@%h --detach \
    --logfile=logs/celery_tier4.log \
    --max-memory-per-child=1000000

# Tier 6 (notifications): Email dispatch + async API key usage tracking
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=5 -Q tier6_notifications -n worker_tier6@%h --detach \
    --logfile=logs/celery_tier6.log

echo "Celery workers started (35 total concurrent processes)."
echo "  - tier1_instant:       8 processes  ~600MB"
echo "  - tier2_fast:          8 processes  ~1.6GB"
echo "  - tier3_medium:        8 processes  ~3.2GB"
echo "  - tier4_telemetry:     6 processes  ~6GB  (capped 1GB/worker)"
echo "  - tier6_notifications: 5 processes  ~250MB"

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
echo "    - Processes: 4"
echo "    - Using asyncio event loops (thousands of connections/process)"
echo "  Workers (Celery):"
echo "    - Total processes: 35"
echo "    - Using prefork (process isolation for CPU-bound work)"
echo "    - Tier 4 capped at 1GB/worker via --max-memory-per-child"
echo ""
echo "  Redis:"
echo "    - maxmemory: 3gb (set in /etc/redis/redis.conf)"
echo "    - maxmemory-policy: allkeys-lru"
echo "    - Ensure maxclients >= 100 (check: redis-cli CONFIG GET maxclients)"
echo "    - Django cache: 1 pool (config in settings.py)"
echo "    - Pub/sub service: Dedicated connection (pubsub.py)"
echo ""
echo "  RAM Allocation (revised):"
echo "    - API + Redis + PG:  ~4.5GB"
echo "    - Tier 1 + 6:        ~850MB"
echo "    - Tier 2:            ~1.6GB"
echo "    - Tier 3:            ~3.2GB"
echo "    - Tier 4 telemetry:  ~6GB"
echo "    - Total:             ~16.15GB / 24GB (~7.85GB buffer)"
echo ""
echo "  Streaming (SSE + Pub/Sub):"
echo "    - No polling overhead (40-second stream timeout)"
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