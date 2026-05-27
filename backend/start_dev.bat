@echo off
echo Starting F1 API development environment...

REM Terminal 1 — Redis (via WSL)
start "Redis" wsl sudo service redis-server start

REM Wait 2 seconds for Redis to start
timeout /t 2 /nobreak > nul

REM Terminal 2 — Gunicorn
start "Gunicorn" cmd /k "cd /d %~dp0 && venv\Scripts\gunicorn f1_project.wsgi:application --workers 2 --threads 8 --bind 127.0.0.1:8000 --reload"

REM Terminal 3 — Celery workers (one per queue with correct concurrency)
start "Worker tier1_instant" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=6 -Q tier1_instant -n worker_tier1@%%h"
start "Worker tier2_fast" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=6 -Q tier2_fast -n worker_tier2@%%h"
start "Worker tier3_medium" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=6 -Q tier3_medium -n worker_tier3@%%h"
start "Worker tier4_telemetry" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=4 -Q tier4_telemetry -n worker_tier4@%%h"
start "Worker tier5_pagination" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=8 -Q tier5_pagination -n worker_tier5@%%h"
start "Worker tier6_notifications" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=4 -Q tier6_notifications -n worker_tier6@%%h"
start "Worker backfill" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=solo --concurrency=2 -Q backfill -n worker_backfill@%%h"

REM Terminal 4 — Celery beat
start "Celery Beat" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project beat --loglevel=info"

REM Terminal 5 — Flower
start "Flower" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project flower --port=5555"

echo All terminals launched.
pause