import os
import pytest
from types import SimpleNamespace

# Ensure Django test settings configured before importing Django-backed modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings_test")



@pytest.mark.django_db
def test_dispatch_canonicalizes_qualifying_session():
    called = {}

    class FakeTask:
        name = "api.tasks.populate_race_results"

        def delay(self, *args, **kwargs):
            called["args"] = args
            return SimpleNamespace(id="fake-celery-id")

    fake = FakeTask()
    task_key = "test:populate_session:2020:2:qualifying"

    # Import TaskManager and TaskRecord here so Django apps are ready (pytest-django will configure)
    from api.queue.manager import TaskManager
    from api.models import TaskRecord

    success = TaskManager._dispatch(task_key, fake, 2020, 2, "QUALIFYING")

    assert success is True
    assert "args" in called
    # First arg to delay is the task_key
    assert called["args"][0] == task_key
    # Session type should be canonicalized to 'Q' at positional index 3
    assert called["args"][3] == "Q"

    # TaskRecord should be created with pending status
    record = TaskRecord.objects.get(task_key=task_key)
    assert record.status == "pending"
    assert record.created_at is not None
