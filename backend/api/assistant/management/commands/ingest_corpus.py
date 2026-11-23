"""Ingest every registered DocumentSource that has no chunks yet (synchronously, with the real embedding model).

  python manage.py ingest_corpus [--force]

Use the `api.assistant.tasks.ingest_pending` task to do the same on the `rag` queue.
"""
from django.core.management.base import BaseCommand

from api.assistant.ingest import ingest_source
from api.assistant.models import DocumentSource


class Command(BaseCommand):
    help = "Parse, chunk, embed and store pending DocumentSource PDFs."

    def add_arguments(self, p):
        p.add_argument("--force", action="store_true", help="re-ingest sources that are already done")

    def handle(self, *a, force, **kw):
        qs = DocumentSource.objects.all() if force else DocumentSource.objects.filter(ingested_at__isnull=True)
        for src in qs.order_by("pk"):
            self.stdout.write(str(ingest_source(src, force=force)))
