#!/bin/bash
# start_prod.sh — Production startup for Oracle Cloud A1 Flex (4 OCPUs, 24GB RAM)
# Place this file in the backend/ directory alongside manage.py
# Run: chmod +x start_prod.sh && ./start_prod.sh

echo "Starting F1 API production environment..."

# ---------------------------------------------------------------------------
# Gunicorn — 9 workers, 2 threads each (18 concurrent slots)
# ---------------------------------------------------------------------------
gunicorn f1_project.wsgi:application \
    --workers 9 \
    --threads 2 \
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

echo "Gunicorn started."

# ---------------------------------------------------------------------------
# Celery workers — one per queue, correct concurrency per tier
# ---------------------------------------------------------------------------
celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier1_instant -n worker_tier1@%h --detach \
    --logfile=logs/celery_tier1.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier2_fast -n worker_tier2@%h --detach \
    --logfile=logs/celery_tier2.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=6 -Q tier3_medium -n worker_tier3@%h --detach \
    --logfile=logs/celery_tier3.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier4_telemetry -n worker_tier4@%h --detach \
    --logfile=logs/celery_tier4.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=8 -Q tier5_pagination -n worker_tier5@%h --detach \
    --logfile=logs/celery_tier5.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=4 -Q tier6_notifications -n worker_tier6@%h --detach \
    --logfile=logs/celery_tier6.log

celery -A f1_project worker --loglevel=info --pool=prefork --concurrency=2 -Q backfill -n worker_backfill@%h --detach \
    --logfile=logs/celery_backfill.log

echo "Celery workers started."

# ---------------------------------------------------------------------------
# Celery beat — scheduler
# ---------------------------------------------------------------------------
celery -A f1_project beat --loglevel=info --detach \
    --logfile=logs/celery_beat.log

echo "Celery beat started."

# ---------------------------------------------------------------------------
# Flower — monitoring UI on port 5555
# ---------------------------------------------------------------------------
celery -A f1_project flower --port=5555 --detach \
    --logfile=logs/flower.log

echo "Flower started at http://localhost:5555"
echo ""
echo "All services started. Logs in backend/logs/"
echo "To stop all: pkill -f gunicorn && pkill -f celery"