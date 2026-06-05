@echo off
echo ==========================================
echo PURGING ALL WORKERS, SERVER, AND REDIS
echo ==========================================
echo.

echo 1. Killing all Python processes (Django Server + Celery Workers)...
taskkill /F /IM python.exe /T 2>NUL

echo 2. Flushing Redis Database...
redis-cli flushall

echo.
echo ==========================================
echo PURGE COMPLETE! 
echo You can now restart your Server and Worker cleanly.
echo ==========================================
pause
