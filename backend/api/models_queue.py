"""
Celery task queue record model — distributed lock & visibility layer.

TaskRecord is created immediately when a task is enqueued (status=pending),
before the Celery worker starts executing it. This ensures:
  1. A distributed lock preventing duplicate enqueues (pending/running/complete blocks re-enqueue)
  2. Visibility into task lifecycle (created_at, completed_at)
  3. Error tracking (error_message) for failed tasks that can be re-tried on next request
"""
from django.db import models


class TaskRecord(models.Model):
    """Distributed task queue lock and visibility record."""

    class Status(models.TextChoices):
        PENDING  = "pending",  "Task queued, waiting for worker"
        RUNNING  = "running",  "Task started on worker"
        COMPLETE = "complete", "Task completed successfully, DB row written"
        FAILED   = "failed",   "Task failed, error_message populated"

    task_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique task identifier (e.g., 'standings:2025', 'session:2025:8:R')",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text="Task lifecycle state: pending → running → complete or failed",
    )
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="UUID of the Celery task (set after dispatch)",
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Exception traceback if status=failed",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the task was enqueued",
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the task completed or failed",
    )
    
    class Meta:
        db_table = "celery_task_record"
        constraints = []
        indexes = [
            models.Index(fields=["status"], name="idx_task_record_status"),
            models.Index(fields=["task_key", "status"], name="idx_task_record_key_status"),
        ]
    
    def __str__(self):
        return f"TaskRecord({self.task_key}, {self.status})"
