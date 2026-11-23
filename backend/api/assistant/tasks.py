"""Celery tasks for the assistant app (routed to the `rag` queue by module)."""
from __future__ import annotations

from celery import shared_task

from .ingest import ingest_source as _ingest
from .models import DocumentSource


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
