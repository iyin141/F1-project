import os
import pytest
from types import SimpleNamespace

# Ensure Django test settings configured before importing Django-backed modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings_test")

from api.common.constants import clean_session_type


@pytest.mark.parametrize(
    "input_val,expected",
    [
        (None, "R"),
        ("race", "R"),
        ("R", "R"),
        ("races", "R"),
        ("qualifying", "Q"),
        ("qual", "Q"),
        ("Q", "Q"),
        ("sprint", "S"),
        ("s", "S"),
        ("S", "S"),
        ("practice 1", "FP1"),
        ("practice_2", "FP2"),
        ("sprint_shootout", "SQ"),
        ("sprint_qualifying", "SQ"),
        # Short codes — critical for seed worker dispatch
        ("FP1", "FP1"),
        ("FP2", "FP2"),
        ("FP3", "FP3"),
        ("SQ", "SQ"),
    ],
)
def test_clean_session_type_various(input_val, expected):
    assert clean_session_type(input_val) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "raw_session,expected_code",
    [
        ("race", "R"),
        ("QUALIFYING", "Q"),
        ("sprint", "S"),
        ("practice 1", "FP1"),
    ],
)
def test_dispatch_cleans_session_for_multiple_tasks(raw_session, expected_code):
    called = {}

    class FakeTask:
        name = "api.tasks.populate_race_results"

        def delay(self, *args, **kwargs):
            called["args"] = args
            return SimpleNamespace(id=f"fake-{expected_code}-id")

    fake = FakeTask()
    task_key = f"test:populate_race_results:2021:5:{raw_session}"

    # Import TaskManager and TaskRecord here so Django apps are ready (pytest-django will configure)
    from api.queue.manager import TaskManager
    from api.models import TaskRecord

    success = TaskManager._dispatch(task_key, fake, 2021, 5, raw_session)

    assert success is True
    assert "args" in called
    # First arg is task_key
    assert called["args"][0] == task_key
    # Ensure canonicalized session code placed at positional index 3
    assert called["args"][3] == expected_code

    record = TaskRecord.objects.get(task_key=task_key)
    assert record.status == "pending"
    assert record.created_at is not None
