"""Celery tasks for the assistant app (routed to the `rag` queue by module)."""
from __future__ import annotations

import logging

from celery import shared_task

from .ingest import ingest_source as _ingest
from .models import DocumentSource

logger = logging.getLogger(__name__)


@shared_task(name="api.assistant.tasks.ingest_document", max_retries=0)
def ingest_document(source_id: int, force: bool = False) -> dict:
    """Parse, chunk, embed and store one DocumentSource. A repeat call for an ingested source does nothing."""
    return _ingest(DocumentSource.objects.get(pk=source_id), force=force)


@shared_task(name="api.assistant.tasks.ingest_pending", max_retries=0)
def ingest_pending(limit: int | None = None) -> dict:
    """Fan out ingest_document for every source without chunks yet (each its own task, so one bad PDF
    does not block the rest)."""
    ids = list(DocumentSource.objects.filter(ingested_at__isnull=True).order_by("pk").values_list("pk", flat=True)[:limit])
    for i in ids:
        ingest_document.delay(i)
    return {"enqueued": len(ids)}


def _runner():
    from .llm import ClaudeRunner

    return ClaudeRunner()


# Tests replace this factory with one returning a FakeRunner (live `claude` is never started in tests).
RUNNER_FACTORY = _runner


@shared_task(name="api.assistant.tasks.ask_question", max_retries=0, soft_time_limit=240, time_limit=300)
def ask_question(task_key: str, question: str, year: int | None = None, round_number: int | None = None) -> dict:
    """Answer one question on the rag worker: retrieval and the headless Claude calls run here, never in web.
    Every event goes to the task's event stream; the stream always ends with `done` or `error`."""
    from celery.exceptions import SoftTimeLimitExceeded

    from .agent import run_agent
    from .sse import get_bus

    bus = get_bus()
    ended = []

    def emit(event: dict) -> None:
        if event.get("type") in ("done", "error"):
            ended.append(event["type"])
        bus.publish(task_key, event)

    try:
        result = run_agent(question, year, round_number, runner=RUNNER_FACTORY(), emit=emit)
    except SoftTimeLimitExceeded:
        emit({"type": "error", "code": "timeout", "message": "The assistant took too long; try again."})
        result = {}
    if not ended:  # belt and braces: a reader must never wait for an event that will not come
        emit({"type": "error", "code": "internal", "message": "The assistant stopped without an answer."})
    return {"task_key": task_key, "ended": ended[-1] if ended else None, "grounded": result.get("grounded")}
