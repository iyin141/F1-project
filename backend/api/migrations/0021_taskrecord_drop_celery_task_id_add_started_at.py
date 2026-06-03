"""
Migration 0021: Drop celery_task_id from TaskRecord, add started_at.

Part of SSE migration — workers now publish results via Redis pub/sub instead
of updating a Celery task ID. started_at records when the worker began executing.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0020_taskrecord_meta"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="taskrecord",
            name="celery_task_id",
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="started_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When the worker started executing the task",
            ),
        ),
    ]
