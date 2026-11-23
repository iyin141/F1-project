"""Ingestion on the SQLite test DB: parser on a generated PDF, mocked embedder, idempotency. No network, no model."""
import pytest

from api.assistant import ingest, tasks
from api.assistant.models import EMBED_DIM, DocChunk
from api.assistant.tests.pdf_fixture import make_pdf
from api.assistant.fetch import Candidate, store_pdf

PAGES = [
    ["ARTICLE B9: PERSONNEL LIMITATIONS", "B9.1 General Provisions",
     "B9.1.1 Each Competitor must declare its personnel before the Competition."],
    ["B9.2 Operational Personnel", "B9.2.1 Operational personnel are limited to the number in the table."],
]


class FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        return [[float(i % 7)] * EMBED_DIM for i, _ in enumerate(texts)]


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARDS_DATA_DIR", str(tmp_path))
    src, _ = store_pdf(Candidate("https://www.fia.com/reg.pdf", "sporting_regs", 2026, "", "reg"), make_pdf(PAGES), tmp_path)
    return src


@pytest.mark.django_db
def test_parse_pdf_reads_text_per_page(source, tmp_path):
    pages = ingest.parse_pdf(tmp_path / source.file_path)
    assert [n for n, _ in pages] == [1, 2]
    assert "B9.1.1" in pages[0][1] and "B9.2.1" in pages[1][1]


@pytest.mark.django_db
def test_ingest_writes_chunks_with_metadata(source):
    emb = FakeEmbedder()
    res = ingest.ingest_source(source, embed=emb)
    assert res["status"] == "ingested" and res["chunks"] == DocChunk.objects.count() >= 1
    c = DocChunk.objects.first()
    assert c.article.startswith("B9") and c.page == 1 and "B9" in c.section
    assert len(c.embedding) == EMBED_DIM
    source.refresh_from_db()
    assert source.ingested_at and source.page_count == 2


@pytest.mark.django_db
def test_reingest_same_source_does_nothing(source):
    emb = FakeEmbedder()
    ingest.ingest_source(source, embed=emb)
    before = list(DocChunk.objects.values_list("pk", flat=True))
    res = ingest.ingest_source(source, embed=emb)
    assert res["status"] == "skipped" and emb.calls == 1  # no second embedding call
    assert list(DocChunk.objects.values_list("pk", flat=True)) == before
    # the same bytes under another URL never become a second source, so never a second set of chunks
    again, created = store_pdf(Candidate("https://www.fia.com/mirror.pdf", "sporting_regs", 2026), make_pdf(PAGES))
    assert not created and again.pk == source.pk


@pytest.mark.django_db
def test_failed_embedding_leaves_source_pending(source):
    def boom(_):
        raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        ingest.ingest_source(source, embed=boom)
    source.refresh_from_db()
    assert source.ingested_at is None and DocChunk.objects.count() == 0
    assert ingest.ingest_source(source, embed=FakeEmbedder())["status"] == "ingested"  # retry succeeds


@pytest.mark.django_db
def test_force_replaces_chunks(source):
    ingest.ingest_source(source, embed=FakeEmbedder())
    n = DocChunk.objects.count()
    ingest.ingest_source(source, embed=FakeEmbedder(), force=True)
    assert DocChunk.objects.count() == n


@pytest.mark.django_db
def test_task_is_on_rag_queue_and_idempotent(source, monkeypatch):
    from django.conf import settings

    assert settings.CELERY_TASK_ROUTES["api.assistant.tasks.*"] == {"queue": "rag"}
    assert tasks.ingest_document.name.startswith("api.assistant.tasks.")
    emb = FakeEmbedder()
    monkeypatch.setattr("api.assistant.embeddings.embed_texts", emb)
    assert tasks.ingest_document.delay(source.pk).get()["status"] == "ingested"
    assert tasks.ingest_document.delay(source.pk).get()["status"] == "skipped"
    assert tasks.ingest_pending.delay().get() == {"enqueued": 0}
