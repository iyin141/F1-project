"""Tests with a mocked transport: no network, no server."""
import json

import httpx
import pytest

from f1controlroom import (
    AuthError, BadRequest, F1Client, F1Error, NotFound, PendingError, PendingTimeout, RateLimited, ServiceUnavailable,
)
from f1controlroom.sse import parse_sse


def make(handler, **kw):
    sleeps = []
    c = F1Client("k-123", "https://api.test", client=httpx.Client(transport=httpx.MockTransport(handler)),
                 sleep=sleeps.append, **kw)
    c.sleeps = sleeps
    return c


def sse(*frames):
    out = ""
    for i, (event, data) in enumerate(frames):
        out += f"id: {i}\nevent: {event}\ndata: {json.dumps(data)}\n\n"
    return out


SSE_HEADERS = {"content-type": "text/event-stream"}


def test_auth_header_url_and_param_encoding():
    seen = {}

    def handler(req):
        seen["req"] = req
        return httpx.Response(200, json={"ok": True})

    c = make(handler)
    assert c.telemetry(2026, 5, driver="NOR", lap=10, channels=["speed", "throttle"], format="columnar",
                       start_m=1000) == {"ok": True}
    req = seen["req"]
    assert req.headers["x-api-key"] == "k-123"
    assert req.url.path == "/api/analysis/races/2026/5/telemetry/"
    assert dict(req.url.params) == {"driver": "NOR", "lap": "10", "channels": "speed,throttle",
                                    "format": "columnar", "start_m": "1000"}  # None params are dropped


def test_base_url_may_already_end_in_api():
    c = F1Client("k", "https://x.test/api/", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=r.url.path))))
    assert c.schedule(2026) == "/api/races/2026/"


@pytest.mark.parametrize("status,exc", [(400, BadRequest), (401, AuthError), (403, AuthError), (404, NotFound),
                                        (429, RateLimited)])
def test_error_mapping(status, exc):
    c = make(lambda r: httpx.Response(status, json={"detail": "nope"}, headers={"Retry-After": "7"}))
    with pytest.raises(exc) as e:
        c.results(2026, 1)
    assert e.value.status == status and "nope" in str(e.value)
    if status == 429:
        assert e.value.retry_after == 7


def test_202_raises_pending_with_task_key():
    c = make(lambda r: httpx.Response(202, json={"status": "pending", "task_key": "track_map:2026:5:distance", "detail": "queued"}))
    with pytest.raises(PendingError) as e:
        c.track_map(2026, 5)
    assert e.value.task_key == "track_map:2026:5:distance"


def test_wait_polls_until_ready():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(202, json={"status": "pending", "task_key": "t"}, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"points": [1, 2]})

    c = make(handler)
    assert c.track_map(2026, 5, wait=30) == {"points": [1, 2]}
    assert len(calls) == 3 and c.sleeps == [1.0, 1.0]


def test_wait_gives_up_with_pending_timeout():
    c = make(lambda r: httpx.Response(202, json={"status": "pending"}), wait=0.001)
    c._sleep = lambda s: __import__("time").sleep(0.01)
    with pytest.raises(PendingTimeout):
        c.chaos_race(2026, 5)


def test_503_retries_after_retry_after_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"status": "failed", "reason": "no laps"}, headers={"Retry-After": "300"})
        return httpx.Response(200, json={"ok": 1})

    c = make(handler)  # Retry-After 300 is capped by max_retry_after (30)
    assert c.track_map(2026, 5) == {"ok": 1}
    assert c.sleeps == [30.0]


def test_503_raises_when_retries_are_used_up():
    c = make(lambda r: httpx.Response(503, json={"retry_after": 12, "reason": "recent failure"}), retries=1)
    with pytest.raises(ServiceUnavailable) as e:
        c.mini_sectors(2026, 5, drivers=["NOR", "VER"])
    assert e.value.retry_after == 12 and len(c.sleeps) == 1


def test_v1_miss_returns_the_single_sse_frame_as_json():
    c = make(lambda r: httpx.Response(200, headers=SSE_HEADERS, content='data: {"status": "complete", "data": [1]}\n\n'))
    assert c.laps(2026, 5) == {"status": "complete", "data": [1]}


def test_parse_sse_handles_comments_multiline_and_non_json():
    evs = list(parse_sse([": keep-alive", "id: 4", "event: token", 'data: {"text": "a"}', "", "data: plain", ""]))
    assert (evs[0].event, evs[0].id, evs[0].data) == ("token", 4, {"text": "a"})
    assert (evs[1].event, evs[1].data) == ("message", {"raw": "plain"})


def test_ask_streams_events_in_order():
    body = sse(("status", {"type": "status", "phase": "queued", "task_key": "ask-" + "a" * 32}),
               ("token", {"type": "token", "text": "Hel"}), ("token", {"type": "token", "text": "lo [E1]"}),
               ("citations", {"type": "citations", "citations": [{"page": 14}]}),
               ("done", {"type": "done", "grounded": True}))
    seen = {}

    def handler(req):
        seen["req"] = req
        return httpx.Response(200, headers=SSE_HEADERS, content=body)

    c = make(handler)
    events = list(c.ask("What is the penalty for causing a collision?", year=2026))
    assert [e.event for e in events] == ["status", "token", "token", "citations", "done"]
    assert seen["req"].method == "POST" and seen["req"].url.path == "/api/assistant/ask"
    assert json.loads(seen["req"].content) == {"question": "What is the penalty for causing a collision?", "year": 2026}
    ans = c.ask_answer("q q q", year=2026)
    assert ans.text == "Hello [E1]" and ans.citations == [{"page": 14}] and ans.done["grounded"] is True


def test_ask_error_event_is_yielded_and_ask_answer_raises():
    body = sse(("status", {"task_key": "ask-" + "b" * 32}), ("error", {"type": "error", "code": "rate_limited", "message": "later"}))
    c = make(lambda r: httpx.Response(200, headers=SSE_HEADERS, content=body))
    assert list(c.ask("question"))[-1].data["code"] == "rate_limited"
    with pytest.raises(F1Error, match="rate_limited"):
        c.ask_answer("question")


class Breaks(httpx.SyncByteStream):
    def __init__(self, head):
        self.head = head

    def __iter__(self):
        yield self.head.encode()
        raise httpx.ReadError("connection reset")


def test_ask_resumes_after_a_dropped_connection_without_repeating_tokens():
    key = "ask-" + "c" * 32
    first = sse(("status", {"task_key": key}), ("token", {"text": "A"}))
    rest = "id: 2\nevent: token\ndata: " + json.dumps({"text": "B"}) + "\n\n" + \
           "id: 3\nevent: done\ndata: " + json.dumps({"grounded": True}) + "\n\n"
    seen = []

    def handler(req):
        seen.append(req)
        if req.method == "POST":
            return httpx.Response(200, headers=SSE_HEADERS, stream=Breaks(first))
        return httpx.Response(200, headers=SSE_HEADERS, content=rest)

    c = make(handler)
    assert c.ask_answer("question").text == "AB"
    resume = seen[1]
    assert resume.url.path == f"/api/assistant/ask/{key}/events" and resume.headers["last-event-id"] == "1"


def test_ask_http_error_before_stream_is_raised():
    c = make(lambda r: httpx.Response(400, json={"error": {"question": ["too short"]}}))
    with pytest.raises(BadRequest):
        list(c.ask("hi"))


def test_ask_events_sends_last_event_id():
    seen = {}

    def handler(req):
        seen["h"] = req.headers.get("last-event-id")
        return httpx.Response(200, headers=SSE_HEADERS, content=sse(("done", {"grounded": False})))

    c = make(handler)
    assert [e.event for e in c.ask_events("ask-" + "d" * 32, last_event_id=5)] == ["done"]
    assert seen["h"] == "5"
