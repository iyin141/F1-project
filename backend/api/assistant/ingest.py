"""PDF -> chunks -> embeddings -> DocChunk rows. Idempotent and all-or-nothing per document.

Parser: pypdf (BSD, pure Python): installs anywhere, arm64 included, no native library and no torch. Cost:
about 0.5 s per page (the 101-page Sporting Regulations take about a minute), acceptable for a one-off
background job. PyMuPDF is 50x faster but AGPL; pdfplumber/pdfminer are slower still. These PDFs are
text PDFs with single-column layout, so extraction quality is not the constraint.

Idempotency (lessons from the reference pipeline's ledger): the "done" marker (`ingested_at`) is written in the
SAME transaction as the chunks, so there is no state with vectors but no ledger row, or the reverse. Embedding
happens before the transaction opens, so a failed model call leaves the source untouched and pending.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone

from .chunking import Chunk, chunk_pages, embedding_input
from .fetch import data_dir
from .models import DocChunk, DocumentSource

logger = logging.getLogger(__name__)


def parse_pdf(path: Path) -> list[tuple[int, str]]:
    """[(1-based page number, text)] for every page."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(i, (page.extract_text() or "")) for i, page in enumerate(reader.pages, start=1)]


def _fill_tsvector(source: DocumentSource) -> None:
    if connection.vendor != "postgresql":  # SQLite (unit tests) has no tsvector
        return
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE assistant_docchunk SET search_vector = to_tsvector('english', text) WHERE source_id = %s",
            [source.pk],
        )


def ingest_source(source: DocumentSource, embed=None, force: bool = False, parse=parse_pdf) -> dict:
    """Ingest one DocumentSource. `embed(list[str]) -> list[list[float]]` defaults to the bge-small model."""
    if source.ingested_at and not force:
        return {"status": "skipped", "source_id": source.pk, "chunks": source.chunks.count()}
    pages = parse(data_dir() / source.file_path)
    chunks: list[Chunk] = chunk_pages(pages)
    if not chunks:
        raise ValueError(f"no text extracted from {source.file_path} (scanned PDF? OCR is out of scope)")
    if embed is None:
        from .embeddings import embed_texts as embed
    vectors = embed([embedding_input(c) for c in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks")
    rows = [
        DocChunk(source=source, chunk_index=i, text=c.text, embedding=v, page=c.page, section=c.section[:300],
                 article=c.article[:40], token_estimate=c.tokens)
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]
    with transaction.atomic():
        source.chunks.all().delete()  # only reached on force=True or a never-ingested source
        DocChunk.objects.bulk_create(rows, batch_size=200)
        _fill_tsvector(source)
        source.page_count = len(pages)
        source.ingested_at = timezone.now()
        source.save(update_fields=["page_count", "ingested_at"])
    logger.info("[assistant] ingested source=%s chunks=%d", source.pk, len(rows))
    return {"status": "ingested", "source_id": source.pk, "chunks": len(rows)}
