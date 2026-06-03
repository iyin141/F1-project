import json
import os
import sys
import types

# Avoid importing real Django models at collection time by stubbing the queue manager.
class _FakeTaskManager:
    @staticmethod
    def get_existing_task(tk):
        return None

    @staticmethod
    def enqueue_if_needed(task_key, fn, *a, **kw):
        return None

sys.modules.setdefault("api.queue.manager", types.SimpleNamespace(TaskManager=_FakeTaskManager))

# Ensure Django test settings are used so `django.core.cache` and other
# Django imports configure correctly during module import.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings_test")

from api.services.nonblocking import handle_data_request
from api.services import streaming
from api.queue import manager as queue_manager


def test_handle_data_request_cache_hit(monkeypatch):
    # Cache returns serialized JSON. Patch the cache used inside nonblocking module.
    # Ensure function treats cache as active (not test env)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "not_test")
    monkeypatch.setattr("api.services.nonblocking.cache.get", lambda k: json.dumps({"cached": True}))

    resp = handle_data_request(
        cache_key="k1",
        db_fetch_fn=lambda: (_ for _ in ()).throw(Exception("should not call DB")),
        task_fn=None,
        task_key="t1",
    )

    assert resp.status_code == 200
    assert resp.data == {"cached": True}


def test_handle_data_request_db_hit_backfills(monkeypatch):
    # Cache miss, DB returns data and backfill should call set_in_cache
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "not_test")
    monkeypatch.setattr("api.services.nonblocking.cache.get", lambda k: None)
    set_calls = []
    monkeypatch.setattr("api.services.nonblocking.set_in_cache", lambda key, val, ttl: set_calls.append((key, val, ttl)))

    db_data = {"from_db": 1}

    resp = handle_data_request(
        cache_key="k2",
        db_fetch_fn=lambda: db_data,
        task_fn=None,
        task_key="t2",
        cache_ttl=60,
    )

    assert resp.status_code == 200
    assert resp.data == db_data
    assert set_calls, "Expected cache backfill to be called"


def test_handle_data_request_enqueue_and_stream(monkeypatch):
    # Cache miss, DB miss -> should enqueue and return streaming response
    monkeypatch.setattr("api.services.nonblocking.cache.get", lambda k: None)
    monkeypatch.setattr(queue_manager.TaskManager, "get_existing_task", lambda tk: None)
    enqueued = []
    monkeypatch.setattr(queue_manager.TaskManager, "enqueue_if_needed", lambda task_key, fn, *a, **kw: enqueued.append(task_key))

    sentinel = object()
    monkeypatch.setattr(streaming, "stream_task_result", lambda tk: sentinel)

    resp = handle_data_request(
        cache_key="k3",
        db_fetch_fn=lambda: None,
        task_fn=lambda *a, **kw: None,
        task_key="t3",
    )

    assert resp is sentinel
    assert enqueued == ["t3"]
