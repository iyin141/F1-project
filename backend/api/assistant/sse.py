"""Multi-event stream for /api/assistant/ask.

The existing helpers (`api.services.streaming.stream_task_result*`) deliver exactly ONE frame per task and stop, so
they cannot carry status, token, citations and done. This module keeps their conventions (the raw publish client and
REDIS_URL from `api.services.pubsub`, an async generator inside a `StreamingHttpResponse`, no-cache and
X-Accel-Buffering headers) and adds what a multi-event stream needs: the worker appends each event to a Redis list
(so a reader that connects late, or reconnects, replays from the start: pub/sub alone loses messages published
before the subscriber is ready) and the stream reads that list.

Frame format: `id: <seq>`, `event: <type>`, `data: <json>`. Terminal events: done, error.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

TERMINAL = ("done", "error")
KEY_TTL = 900          # events are kept 15 minutes
STREAM_TIMEOUT = 300   # wall-clock limit per stream
KEEPALIVE = 15


def _key(task_key: str) -> str:
    return f"assistant:ask:{task_key}"


class RedisEventBus:
    def publish(self, task_key: str, event: dict) -> None:
        from api.services.pubsub import redis_publish_client  # reuse the shared publish client

        try:
            pipe = redis_publish_client.pipeline()
            pipe.rpush(_key(task_key), json.dumps(event))
            pipe.expire(_key(task_key), KEY_TTL)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.error("assistant.publish_failed task_key=%s error=%s", task_key, exc)

    def exists(self, task_key: str) -> bool:
        from api.services.pubsub import redis_publish_client

        try:
            return bool(redis_publish_client.exists(_key(task_key)))
        except Exception:  # noqa: BLE001
            return False

    async def read(self, task_key: str, start: int) -> list[dict]:
        import redis.asyncio as aioredis

        from api.services.pubsub import REDIS_URL

        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            return [json.loads(x) for x in await client.lrange(_key(task_key), start, -1)]
        finally:
            await client.aclose()


class MemoryEventBus:
    """In-process bus for tests (same interface)."""

    def __init__(self):
        self.events: dict[str, list[dict]] = {}

    def publish(self, task_key: str, event: dict) -> None:
        self.events.setdefault(task_key, []).append(event)

    def exists(self, task_key: str) -> bool:
        return task_key in self.events

    async def read(self, task_key: str, start: int) -> list[dict]:
        return list(self.events.get(task_key, []))[start:]


_bus = None


def get_bus():
    global _bus
    if _bus is None:
        _bus = RedisEventBus()
    return _bus


def set_bus(bus) -> None:
    global _bus
    _bus = bus


def frame(seq: int, event: dict) -> str:
    return f"id: {seq}\nevent: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def event_stream(task_key: str, bus=None, start: int = 0, timeout: float = STREAM_TIMEOUT, poll: float = 0.2):
    bus = bus or get_bus()
    seq, t0, last = start, time.monotonic(), time.monotonic()
    while True:
        events = await bus.read(task_key, seq)
        for ev in events:
            yield frame(seq, ev)
            seq += 1
            last = time.monotonic()
            if ev.get("type") in TERMINAL:
                return
        now = time.monotonic()
        if now - t0 > timeout:
            yield frame(seq, {"type": "error", "code": "timeout", "message": "The assistant took too long; try again."})
            return
        if now - last > KEEPALIVE:
            yield ": keepalive\n\n"
            last = now
        await asyncio.sleep(poll)


def sse_response(task_key: str, bus=None, start: int = 0) -> StreamingHttpResponse:
    resp = StreamingHttpResponse(event_stream(task_key, bus, start), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp
