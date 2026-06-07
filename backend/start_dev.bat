@echo on
echo Starting F1 API development environment...
echo.
echo NOTE: Using --pool=threads for proper concurrent task processing on Windows
echo.
echo Memory profile (dev — threads, not prefork):
echo   - tier1_instant:       5 threads  (lightweight, ~75MB equiv)
echo   - tier2_fast:          5 threads  (race/qualifying results, ~200MB equiv)
echo   - tier3_medium:        4 threads  (pace analysis, stints, ~400MB equiv)
echo   - tier4_telemetry:     4 threads  (FastF1 heavy I/O, capped ~1GB)
echo   - tier6_notifications: 4 threads  (email/alerts, ~50MB equiv)
echo   Note: Windows uses thread pool — memory caps are not enforced here.
echo         Test heavy Tier 4 tasks carefully on dev to avoid OOM.
echo.

REM Terminal 1 — Django development server (optional, for debugging)
REM start "Django Dev Server" cmd /k "cd /d %~dp0 && venv\Scripts\python manage.py runserver 0.0.0.0:8001"

REM Terminal 2 — Waitress (production-like WSGI server)
start "Waitress" cmd /k "cd /d %~dp0 && venv\Scripts\waitress-serve --port=8000 --threads=8 f1_project.wsgi:application"

REM Terminal 3 — Celery workers (one per queue with THREADS pool for concurrency on Windows)

REM Tier 1 (instant): High priority — standings, schedules, driver career — 5 threads
start "Worker tier1_instant" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=5 -Q tier1_instant -n worker_tier1@%%h"

REM Tier 2 (fast): Most common tasks — race/qualifying results, weather, pit stops — 5 threads
start "Worker tier2_fast" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=5 -Q tier2_fast -n worker_tier2@%%h"

REM Tier 3 (medium): Complex session calculations — pace analysis, stints, sectors — 4 threads
start "Worker tier3_medium" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier3_medium -n worker_tier3@%%h"

REM Tier 4 (telemetry): Heavy FastF1 downloads — raw speed/rpm/throttle data — 4 threads
REM NOTE: No --max-memory-per-child on Windows (prefork only). Monitor manually.
start "Worker tier4_telemetry" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier4_telemetry -n worker_tier4@%%h"

REM Tier 6 (notifications): Email dispatch + async API key usage tracking — 4 threads
start "Worker tier6_notifications" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier6_notifications -n worker_tier6@%%h"

REM Terminal 4 — Celery beat (scheduler)
start "Celery Beat" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project beat --loglevel=info"

REM Terminal 5 — Flower (monitoring dashboard at http://localhost:5555)
start "Flower" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project flower --port=5555"

echo.
echo ============================================================
echo All terminals launched successfully!
echo.
echo Services:
echo   - API Server:     http://localhost:8000
echo   - Flower Monitor: http://localhost:5555
echo.
echo Worker pool: threads (Windows — prefork not supported)
echo   Prod uses prefork with --max-memory-per-child=1000000 on Tier 4.
echo   Dev threads share memory — avoid running multiple heavy Tier 4
echo   tasks simultaneously to prevent OOM on local machine.
echo.
echo Tier breakdown:
echo   - tier1_instant:       5 threads  (instant responses)
echo   - tier2_fast:          5 threads  (race/qualifying results)
echo   - tier3_medium:        4 threads  (medium operations)
echo   - tier4_telemetry:     4 threads  (FastF1 data — watch memory)
echo   - tier6_notifications: 4 threads  (email/alerts)
echo.
echo Total concurrent tasks: ~22 simultaneous operations
echo.
echo Prod memory targets (enforced on Oracle VM via prefork):
echo   - Redis:           3GB   (maxmemory 3gb in redis.conf)
echo   - Tier 4 workers:  1GB each via --max-memory-per-child
echo   - Total prod RAM:  ~18.15GB / 24GB
echo ============================================================
echo.
pause