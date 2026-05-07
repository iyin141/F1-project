"""
Celery app initialization for F1 backend.

Autodiscovers tasks from all installed apps that have a tasks.py module.
"""
from __future__ import absolute_import

import os
from celery import Celery

# Set the default Django settings module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")

app = Celery("f1_project")

# Load configuration from Django settings, all config keys should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py from all registered Django apps.
app.autodiscover_tasks()
