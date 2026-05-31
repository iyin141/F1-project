"""Management command: diagnose_module1

Runs lightweight diagnostics for Module 1:
- Auth DB-hit repro using `INTERNAL_API_KEY` (captures DB queries during authentication)
- Inspect latest `RaceResultData` payload for missing/unexpected keys

This is safe to run locally; it only reads DB and calls authentication logic.
"""
from __future__ import annotations

import logging
from django.conf import settings
from django.core.management.base import BaseCommand
from rest_framework.test import APIRequestFactory
from rest_framework.request import Request as DRFRequest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.auth import APIKeyAuthentication
from api.models import RaceResultData

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run Module 1 diagnostics: auth DB-hit and persisted payload inspection"

    def handle(self, *args, **options):
        self.stdout.write("Module 1 diagnostics starting...")

        internal_key = getattr(settings, "INTERNAL_API_KEY", None)
        if not internal_key:
            self.stdout.write("INTERNAL_API_KEY not set in settings; set it to run auth repro.")
        else:
            factory = APIRequestFactory()
            # Build a simple GET request with the internal key header
            req = factory.get("/api/_diagnose_auth", HTTP_X_API_KEY=internal_key)
            drf_req = DRFRequest(req)
            auth = APIKeyAuthentication()

            self.stdout.write("Running auth.authenticate() with INTERNAL_API_KEY and capturing DB queries...")
            try:
                with CaptureQueriesContext(connection) as cq:
                    try:
                        result = auth.authenticate(drf_req)
                        self.stdout.write(f"authenticate() returned: {result}")
                    except Exception as exc:  # pragma: no cover - diagnostic
                        self.stdout.write(f"authenticate() raised: {exc}")

                num = len(cq.captured_queries)
                self.stdout.write(f"DB queries during authenticate: {num}")
                for i, q in enumerate(cq.captured_queries[:10], start=1):
                    sql = q.get("sql") if isinstance(q, dict) else str(q)
                    self.stdout.write(f"Q{i}: {sql[:200]}")
            except Exception as exc:  # pragma: no cover - defensive
                self.stdout.write(f"Could not capture DB queries: {exc}")

        # Inspect latest RaceResultData payload
        self.stdout.write("Inspecting latest RaceResultData payload for missing keys...")
        record = RaceResultData.objects.order_by("-id").first()
        if not record:
            self.stdout.write("No RaceResultData rows found in DB.")
            return

        payload = record.payload or {}
        rows_list = payload.get("data") if payload.get("data") is not None else payload.get("results", [])
        self.stdout.write(f"Found {len(rows_list)} rows in latest RaceResultData (id={getattr(record, 'id', '?')})")
        if not rows_list:
            self.stdout.write("No rows found in payload; nothing to inspect.")
            return

        first = rows_list[0]
        sample_keys = list(first.keys())
        self.stdout.write(f"First row keys: {sample_keys}")

        missing = [k for k in ("fastest_lap", "lap_time", "time", "gap") if k not in first]
        if missing:
            self.stdout.write(f"Missing keys in first row: {missing}")
        else:
            self.stdout.write("Common keys present in first row.")
