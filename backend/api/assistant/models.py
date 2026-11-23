"""Stewards assistant corpus: one DocumentSource per fetched PDF, many DocChunk rows per source.

Design for two databases: production/dev run Postgres + pgvector; the unit-test DB is SQLite, where the
`vector` and `tsvector` column types are only names (SQLite accepts any declared type), so the tables
build from these models and the DB-agnostic tests pass. The HNSW and GIN indexes are therefore NOT in
`Meta.indexes` (CREATE INDEX ... USING hnsw cannot run on SQLite): they live in the migration only.
"""
from django.db import models
from pgvector.django import VectorField

EMBED_DIM = 384  # bge-small-en-v1.5


class TSVectorField(models.Field):
    """A bare `tsvector` column. django.contrib.postgres' SearchVectorField needs that app in INSTALLED_APPS
    (a shared setting this app does not own); retrieval uses raw SQL / RawSQL on this column instead."""

    def db_type(self, connection):
        return "tsvector"


class DocType(models.TextChoices):
    SPORTING_REGS = "sporting_regs", "FIA F1 Sporting Regulations"
    TECHNICAL_REGS = "technical_regs", "FIA F1 Technical Regulations"
    OTHER_REGS = "other_regs", "Other FIA F1 regulations (general, financial, operational)"
    STEWARDS_DECISION = "stewards_decision", "Stewards' decision, infringement or summons"
    EVENT_NOTES = "event_notes", "Race director / competition event notes"


class DocumentSource(models.Model):
    url = models.URLField(max_length=500, unique=True)
    doc_type = models.CharField(max_length=24, choices=DocType.choices, db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    race = models.CharField(max_length=120, blank=True, default="", help_text="e.g. 'las vegas grand prix'; empty for regulations")
    title = models.CharField(max_length=300, blank=True, default="")
    sha256 = models.CharField(max_length=64, unique=True)  # the same bytes under two URLs are one source
    fetched_at = models.DateTimeField(auto_now_add=True)
    file_path = models.CharField(max_length=500, help_text="relative to the corpus data dir (STEWARDS_DATA_DIR)")
    page_count = models.PositiveIntegerField(null=True, blank=True)
    ingested_at = models.DateTimeField(null=True, blank=True, help_text="set in the same transaction that writes the chunks")

    class Meta:
        ordering = ["-year", "doc_type", "url"]

    def __str__(self):
        return f"{self.doc_type} {self.year} {self.title or self.url}"


class DocChunk(models.Model):
    source = models.ForeignKey(DocumentSource, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=EMBED_DIM, null=True, blank=True)
    search_vector = TSVectorField(null=True, blank=True, editable=False)  # filled by ingest on Postgres
    page = models.PositiveIntegerField(null=True, blank=True, help_text="1-based page the chunk starts on")
    section = models.CharField(max_length=300, blank=True, default="")
    article = models.CharField(max_length=40, blank=True, default="", help_text="e.g. '33.4'")
    token_estimate = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["source_id", "chunk_index"]
        constraints = [models.UniqueConstraint(fields=["source", "chunk_index"], name="uniq_chunk_per_source")]
