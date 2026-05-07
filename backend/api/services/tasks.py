"""
Deprecated: Legacy django-background-tasks module — replaced by Celery.

All task definitions have been moved to api/tasks.py (@shared_task functions).
All enqueue helpers have been replaced by TaskManager.enqueue_if_needed() calls.

This module is kept only for backward compatibility during migration.
"""
