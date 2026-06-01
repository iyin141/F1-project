@echo on
echo Starting F1 API development environment...
echo.
echo NOTE: Using --pool=threads for proper concurrent task processing on Windows
echo.

REM Terminal 1 — Django development server (optional, for debugging)
REM start "Django Dev Server" cmd /k "cd /d %~dp0 && venv\Scripts\python manage.py runserver 0.0.0.0:8001"

REM Terminal 2 — Waitress (production-like WSGI server)
start "Waitress" cmd /k "cd /d %~dp0 && venv\Scripts\waitress-serve --port=8000 --threads=8 f1_project.wsgi:application"

REM Terminal 3 — Celery workers (one per queue with THREADS pool for concurrency)
REM Tier 1 (instant): High priority, quick responses - 4 threads
start "Worker tier1_instant" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier1_instant -n worker_tier1@%%h"

REM Tier 2 (fast): Most common tasks (results, weather, etc) - 4 threads
start "Worker tier2_fast" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier2_fast -n worker_tier2@%%h"

REM Tier 3 (medium): Medium-duration tasks - 3 threads
start "Worker tier3_medium" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=3 -Q tier3_medium -n worker_tier3@%%h"

REM Tier 4 (telemetry): Data-heavy operations (I/O bound) - 3 threads
start "Worker tier4_telemetry" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=3 -Q tier4_telemetry -n worker_tier4@%%h"

REM Tier 5 (pagination): Pagination and list operations - 4 threads
start "Worker tier5_pagination" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=4 -Q tier5_pagination -n worker_tier5@%%h"

REM Tier 6 (notifications): Email/notifications (I/O bound) - 3 threads
start "Worker tier6_notifications" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=3 -Q tier6_notifications -n worker_tier6@%%h"

REM Backfill worker: Slow/batch operations - 2 threads
start "Worker backfill" cmd /k "cd /d %~dp0 && venv\Scripts\celery -A f1_project worker --loglevel=info --pool=threads --concurrency=2 -Q backfill -n worker_backfill@%%h"

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
echo Changes made:
echo   - pool=solo --^> pool=threads (enables true concurrency)
echo   - Concurrency values adjusted per tier workload
echo.
echo Tier breakdown:
echo   - tier1_instant: 4 threads (instant responses)
echo   - tier2_fast:    4 threads (race/qualifying results)
echo   - tier3_medium:  3 threads (medium operations)
echo   - tier4_telemetry: 3 threads (FastF1 data fetches)
echo   - tier5_pagination: 4 threads (list operations)
echo   - tier6_notifications: 3 threads (email/alerts)
echo   - backfill:      2 threads (slow batch jobs)
echo.
echo Total concurrent tasks: ~24 simultaneous operations
echo ============================================================
echo.
pause