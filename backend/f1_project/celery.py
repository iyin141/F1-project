"""
Celery app initialization for F1 backend.

Autodiscovers tasks from all installed apps that have a tasks.py module.
"""
from __future__ import absolute_import

import os
from celery import Celery
from celery.schedules import crontab
from kombu import Queue

# Set the default Django settings module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")

app = Celery("f1_project")

# Load configuration from Django settings, all config keys should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py from all registered Django apps.
app.autodiscover_tasks()

# Declare named queues so Celery creates them on worker startup.
app.conf.task_queues = (
    Queue("tier1_instant"),
    Queue("tier2_fast"),
    Queue("tier3_medium"),
    Queue("tier4_telemetry"),
    Queue("tier5_pagination"),
    Queue("tier6_notifications"),
    Queue("backfill"),
    Queue("ml"),   # v2: Chaos Point model jobs (worker-ml only)
    Queue("rag"),  # v2: Stewards ingestion and retrieval
)

# Acknowledge tasks only after they complete — tier4 tasks set ack_late=True individually.
app.conf.task_acks_late = False

# Disable worker prefetch so long-running tasks don't starve short ones.
app.conf.worker_prefetch_multiplier = 1

# Beat schedule — periodic tasks.
app.conf.beat_schedule = {
    "check-completed-sessions": {
        "task": "api.tasks.check_for_completed_sessions",
        "schedule": 900,  # every 15 minutes
    },
    "weekly-usage-summary": {
        "task": "api.tasks.send_usage_summary_all",
        "schedule": 604800,  # every 7 days
    },
    # v2 Chaos Point: Monday refreshes the race just run, Wednesday predicts the coming one.
    # Idempotent and data-driven, so off-season runs do nothing harmful.
    "chaos-refresh-monday": {
        "task": "api.chaos.tasks.refresh_chaos",
        "schedule": crontab(minute=0, hour=6, day_of_week="mon"),
    },
    "chaos-refresh-wednesday": {
        "task": "api.chaos.tasks.refresh_chaos",
        "schedule": crontab(minute=0, hour=6, day_of_week="wed"),
    },
}
