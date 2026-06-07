#!/bin/bash
# start_prod.sh — Production startup for Oracle Cloud A1 Flex (4 OCPUs, 24GB RAM)
# Optimized for SSE + Redis pub/sub architecture
# Place this file in the backend/ directory alongside manage.py
# Run: chmod +x start_prod.sh && ./start_prod.sh

echo "Starting F1 API production environment (SSE + Pub/Sub optimized)..."
echo ""

# ---------------------------------------------------------------------------
# Gunicorn — Optimized for SSE streaming
# ---------------------------------------------------------------------------
# CHANGES FROM POLLING MODEL:
#   - Workers: 9 → 9 (unchanged, process-level parallelism stable)
#   - Threads: 2 → 3 (18 slots → 27 slots)
#   - Why: SSE streams don't block threads. One thread can multiplex many
#     open connections. More thread slots = more concurrent HTTP streams
#     without spinning up more processes (which costs more memory/CPU).
#
# Note: With SSE, a client connection doesn't consume a thread while waiting
# for the pub/sub message — the thread yields back to the pool. Gunicorn can
# efficiently handle 27 concurrent HTTP requests on 4 vCPU.
# ---------------------------------------------------------------------------
gunicorn f1_project.wsgi:application \
    --workers 9 \
    --threads 3 \
    --bind 127.0.0.1:8000 \
    --worker-class gthread \
    --worker-tmp-dir /dev/shm \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --timeout 120 \
    --keepalive 5 \
    --access-logfile logs/gunicorn_access.log \
    --error-logfile logs/gunicorn_error.log \
    --log-level info \
    --daemon

echo "Gunicorn started (9 workers × 3 threads = 27 HTTP concurrent slots)."

# ---------------------------------------------------------------------------
# Celery workers — Optimized for pub/sub (no polling overhead)
# ---------------------------------------------------------------------------
# MEMORY PROFILE (revised):
#   - tier1_instant:      8 processes × ~75MB   = ~600MB
#   - tier2_fast:         8 processes × ~200MB  = ~1.6GB
#   - tier3_medium:       8 processes × ~400MB  = ~3.2GB
#   - tier4_telemetry:    8 processes × ~1GB    = ~8GB   ← capped via worker_max_memory_per_child
#   - tier6_notifications:5 processes × ~50MB   = ~250MB
#
# RAM ALLOCATION SUMMARY (revised):
#   - API (Gunicorn):     ~500MB
#   - Redis:              ~3GB    ← provisioned in /etc/redis/redis.conf
#   - PostgreSQL (Neon):  ~1GB
#   - Tier 1 + 6:         ~850MB
#   - Tier 2:             ~1.6GB
#   - Tier 3:             ~3.2GB
#   - Tier 4 (telemetry): ~8GB
#   ─────────────────────────────
#   Total:                ~18.15GB / 24GB  (~5.85GB buffer)
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
#   - tier4_telemetry: 4 → 8 processes, capped at 1GB each (was 1.25GB)
#   - tier5_pagination: Removed (8 processes freed)
#   - backfill:        Removed (2 processes freed)
#   - tier6_notifications: 4 → 5 processes
#   - Redis:           ~500MB → 3GB (maxmemory 3gb in redis.conf)
#
# NEW TOTAL: 37 processes
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
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier4_telemetry -n worker_tier4@%h --detach \
    --logfile=logs/celery_tier4.log \
    --max-memory-per-child=1000000

# Tier 6 (notifications): Email dispatch + async API key usage tracking
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=5 -Q tier6_notifications -n worker_tier6@%h --detach \
    --logfile=logs/celery_tier6.log

echo "Celery workers started (37 total concurrent processes)."
echo "  - tier1_instant:       8 processes  ~600MB"
echo "  - tier2_fast:          8 processes  ~1.6GB"
echo "  - tier3_medium:        8 processes  ~3.2GB"
echo "  - tier4_telemetry:     8 processes  ~8GB  (capped 1GB/worker)"
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
echo "  HTTP Server (Gunicorn):"
echo "    - Processes: 9"
echo "    - Threads per process: 3"
echo "    - Total HTTP slots: 27"
echo ""
echo "  Workers (Celery):"
echo "    - Total processes: 37"
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
echo "    - Tier 4 telemetry:  ~8GB"
echo "    - Total:             ~18.15GB / 24GB (~5.85GB buffer)"
echo ""
echo "  Streaming (SSE + Pub/Sub):"
echo "    - No polling overhead (40-second stream timeout)"
echo "    - Workers publish once, all subscribers notified instantly"
echo "    - Deduplication: multiple requests for same task = one worker task"
echo ""
echo "============================================================"
echo ""
echo "Logs location: backend/logs/"
echo "To stop all services: pkill -f gunicorn && pkill -f celery && pkill -f flower"
echo "To check Redis memory: redis-cli INFO memory | grep used_memory_human"
echo "To check Redis connections: redis-cli INFO stats | grep connected_clients"
echo ""