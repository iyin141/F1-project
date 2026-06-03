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
# BENEFIT OF PUB/SUB:
#   - Workers publish once → all subscribers notified instantly
#   - No status key updates (old polling model had many SET operations)
#   - Freed CPU allows modest concurrency increases
#
# CHANGES:
#   - tier1_instant:  6 → 6 (instant, keep stable)
#   - tier2_fast:     6 → 6 (stable, most common)
#   - tier3_medium:   6 → 6 (stable)
#   - tier4_telemetry: 4 → 5 (I/O bound, +1 for parallelism)
#   - tier5_pagination: 8 → 8 (stable, handles large result sets)
#   - tier6_notifications: 4 → 4 (I/O bound but simpler work)
#   - backfill: 2 → 2 (slow/batch, keep minimal)
#
# NEW TOTAL: 36 → 37 processes (+1 for telemetry parallelism)
# Still safe on 4 vCPU, 24GB RAM with pub/sub efficiency gains.
# ---------------------------------------------------------------------------

# Tier 1 (instant): High priority, quick responses
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier1_instant -n worker_tier1@%h --detach \
    --logfile=logs/celery_tier1.log

# Tier 2 (fast): Most common tasks (results, weather, etc)
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier2_fast -n worker_tier2@%h --detach \
    --logfile=logs/celery_tier2.log

# Tier 3 (medium): Medium-duration tasks
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier3_medium -n worker_tier3@%h --detach \
    --logfile=logs/celery_tier3.log

# Tier 4 (telemetry): Data-heavy I/O operations (FastF1, external APIs)
# INCREASED: 4 → 5 (freed server CPU allows more parallelism on I/O-bound work)
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=5 -Q tier4_telemetry -n worker_tier4@%h --detach \
    --logfile=logs/celery_tier4.log

# Tier 5 (pagination): Pagination and large list operations
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier5_pagination -n worker_tier5@%h --detach \
    --logfile=logs/celery_tier5.log

# Tier 6 (notifications): Email/alerts (I/O bound)
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier6_notifications -n worker_tier6@%h --detach \
    --logfile=logs/celery_tier6.log

# Backfill: Slow/batch operations (keep minimal to avoid starvation)
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=2 -Q backfill -n worker_backfill@%h --detach \
    --logfile=logs/celery_backfill.log

echo "Celery workers started (37 total concurrent processes)."
echo "  - tier1_instant:  6 processes"
echo "  - tier2_fast:     6 processes"
echo "  - tier3_medium:   6 processes"
echo "  - tier4_telemetry: 5 processes [INCREASED from 4]"
echo "  - tier5_pagination: 8 processes"
echo "  - tier6_notifications: 4 processes"
echo "  - backfill:       2 processes"

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
echo "    - Total HTTP slots: 27 (up from 18)"
echo ""
echo "  Workers (Celery):"
echo "    - Total processes: 37 (up from 36)"
echo "    - Using prefork (process isolation for CPU-bound work)"
echo ""
echo "  Redis Connections:"
echo "    - Django cache: 1 pool (config in settings.py)"
echo "    - Pub/sub service: Dedicated connection (pubsub.py)"
echo "    - Ensure Redis maxclients >= 100 (check with: redis-cli CONFIG GET maxclients)"
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
echo "To check Redis connections: redis-cli INFO stats | grep connected_clients"
echo ""