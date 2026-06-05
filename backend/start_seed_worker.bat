@echo off
echo Starting High-Concurrency Celery Worker for Seeding...
echo Listening on queue: tier2_fast
echo Concurrency: 6
echo Pool: gevent
echo Press Ctrl+C to stop the worker when seeding is complete.
echo.
celery -A f1_project worker -Q tier2_fast --concurrency=6 --pool=gevent -n seed_worker@%%h
pause
