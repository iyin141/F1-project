"""POST /api/assistant/ask end to end with a fake runner, in-memory event bus and Celery eager mode."""
import asyncio
import json
import os

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from api.assistant import sse, tasks
from api.assistant.llm import FakeRunner
from api.assistant.retrieval import Hit
from api.assistant.views import AskAPIView
from api.session.views import AnalysisTelemetryAPIView

URL = "/api/assistant/ask"


def a_hit():
    t = "B1.9.5 Penalties for incidents: a time penalty of 5 seconds may be imposed."
    return Hit(1, t, t, 14, "B1.9.5", "B1.9", "https://www.fia.com/x.pdf", "2026 Sporting Regulations", "sporting_regs", 2026, "", 1.0)


@pytest.fixture
def client():
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    return c


@pytest.fixture
def wired(monkeypatch):
    bus = sse.MemoryEventBus()
    sse.set_bus(bus)
    runner = FakeRunner(
        [{"action": "tools", "tool_calls": [{"tool": "search_documents", "args": {"query": "time penalty"}}]}, {"action": "answer"}],
        "A 5 second time penalty may be imposed [E1].", cost_usd=0.02)
    monkeypatch.setattr(tasks, "RUNNER_FACTORY", lambda: runner)
    monkeypatch.setattr("api.assistant.retrieval.retrieve", lambda q, **kw: [a_hit()])
    yield bus, runner
    sse.set_bus(None)


def parse_sse(resp):
    async def collect():
        return b"".join([c async for c in resp.streaming_content])

    body = asyncio.run(collect()).decode()
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        if "data" in lines:
            out.append((lines["event"], json.loads(lines["data"]), lines["id"]))
    return out


def test_stream_event_order_and_content(client, wired):
    resp = client.post(URL, {"question": "What penalty can stewards give?", "year": 2026, "round": 22}, format="json")
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/event-stream")
    assert resp["Cache-Control"] == "no-cache" and resp["X-Accel-Buffering"] == "no"
    ev = parse_sse(resp)
    kinds = [k for k, _, _ in ev]
    assert kinds[0] == "status" and ev[0][1]["phase"] == "queued" and ev[0][1]["task_key"].startswith("ask-")
    assert kinds[-2:] == ["citations", "done"]
    assert kinds.index("token") > kinds.index("status")
    assert [i for _, _, i in ev] == [str(n) for n in range(len(ev))]            # contiguous ids (replayable)
    phases = [d["phase"] for k, d, _ in ev if k == "status"]
    assert phases == ["queued", "solving", "searching", "solving", "composing"]
    cites = next(d for k, d, _ in ev if k == "citations")["citations"]
    assert cites[0]["article"] == "B1.9.5" and cites[0]["page"] == 14 and cites[0]["url"] == "https://www.fia.com/x.pdf"
    done = ev[-1][1]
    assert done["grounded"] and done["cost_usd"] == 0.02
    assert "".join(d["text"] for k, d, _ in ev if k == "token") == done["answer"]


def test_no_evidence_streams_evidence_not_found(client, wired, monkeypatch):
    monkeypatch.setattr("api.assistant.retrieval.retrieve", lambda q, **kw: [])
    ev = parse_sse(client.post(URL, {"question": "Who won the 1950 race?"}, format="json"))
    assert ev[-1][0] == "done" and ev[-1][1]["not_found"] and ev[-1][1]["answer"] == "Evidence not found."


def test_llm_failure_streams_an_error_event_as_the_last_frame(client, wired, monkeypatch):
    from api.assistant.llm import RateLimited

    bus, _ = wired
    monkeypatch.setattr(tasks, "RUNNER_FACTORY", lambda: FakeRunner([RateLimited("limit")]))
    ev = parse_sse(client.post(URL, {"question": "What is a penalty?"}, format="json"))
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "rate_limited" and "done" not in [k for k, _, _ in ev]


@pytest.mark.parametrize("body", [
    {}, {"question": ""}, {"question": "ab"}, {"question": "x" * 1001}, {"question": "ok question", "year": 1900},
    {"question": "ok question", "round": 5}, {"question": "ok question", "year": 2026, "round": 0}, {"question": 5},
])
def test_bad_bodies_are_400_and_nothing_is_enqueued(client, wired, body):
    bus, runner = wired
    r = client.post(URL, body, format="json")
    assert r.status_code == 400 and "error" in r.json()
    assert bus.events == {} and runner.plan_prompts == []


def test_method_not_allowed(client):
    assert client.get(URL).status_code == 405


# ---- auth / throttle parity with an existing analysis view -------------------------

def test_view_classes_match_existing_analysis_view():
    ref = AnalysisTelemetryAPIView
    assert AskAPIView.authentication_classes == ref.authentication_classes
    assert AskAPIView.permission_classes == ref.permission_classes
    assert AskAPIView.throttle_classes == ref.throttle_classes
    assert [c.__name__ for c in AskAPIView.throttle_classes] == ["APIKeyThrottle"]


def test_request_without_api_key_is_rejected_like_existing_views(db):
    r = APIClient().post(URL, {"question": "What is a penalty?"}, format="json")
    assert r.status_code in (401, 403)
    assert r.status_code == APIClient().get("/api/analysis/races/2025/5/laps/").status_code


def test_endpoint_type_is_set_before_the_throttle_runs(monkeypatch, db):
    """The throttle reads request.endpoint_type to price the call; it must already be set when it runs."""
    from api import throttling

    seen = {}
    real = throttling.APIKeyThrottle.allow_request

    def spy(self, request, view):
        seen["cost"] = throttling.get_endpoint_cost(request)
        seen["type"] = getattr(request, "endpoint_type", None)
        return real(self, request, view)

    monkeypatch.setattr(throttling.APIKeyThrottle, "allow_request", spy)
    monkeypatch.setitem(throttling.ENDPOINT_COSTS, "assistant_ask", 10)  # what the orchestrator will add
    c = APIClient()
    c.credentials(HTTP_X_API_KEY=str(settings.INTERNAL_API_KEY))
    c.post(URL, {"q": 1}, format="json")
    assert seen["type"] == "assistant_ask" and seen["cost"] == 10


def test_task_is_routed_to_the_rag_queue_and_never_loads_onnx_in_web():
    assert settings.CELERY_TASK_ROUTES["api.assistant.tasks.*"] == {"queue": "rag"}
    assert tasks.ask_question.name == "api.assistant.tasks.ask_question"
    import subprocess
    import sys
    from pathlib import Path

    code = ("import os, sys, django; os.environ['DJANGO_SETTINGS_MODULE']='f1_project.settings_test'; django.setup(); "
            "import api.assistant.views, api.assistant.sse, api.assistant.tasks; "
            "print(any(m.split('.')[0] in ('onnxruntime', 'fastembed', 'tokenizers') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=120,
                         env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})  # settings_test sets PYTHONPATH to f1_project/, which shadows celery
    assert out.stdout.strip().splitlines()[-1:] == ["False"], (out.stdout[-300:], out.stderr[-800:])
