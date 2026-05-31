"""
Test helpers for the `api.tests` package.

Provide a TestCase mixin that ensures test clients send the
`INTERNAL_API_KEY` as `HTTP_X_API_KEY` so tests can opt-in explicitly
to exercising real auth paths without middleware-side effects.
"""
from __future__ import annotations

import os
from django.conf import settings
from django.test.client import Client

try:
    from rest_framework.test import APIClient
except Exception:  # pragma: no cover - defensive for environments without DRF
    APIClient = None


class TestDefaultAPIKeyMixin:
    """Mixin to ensure test clients include the `INTERNAL_API_KEY` header.

    Usage:
        class MyTests(TestDefaultAPIKeyMixin, TestCase):
            ...

    The mixin is intentionally defensive: it sets `Client.defaults` and
    `APIClient.defaults` when available and avoids raising during setup.
    """

    def setUp(self):
        # Set client defaults first so TestCase creates the client with the header.
        internal_key = os.environ.get("INTERNAL_API_KEY") or getattr(settings, "INTERNAL_API_KEY", None)
        if internal_key:
            try:
                if getattr(Client, "defaults", None) is None:
                    Client.defaults = {}
                Client.defaults.setdefault("HTTP_X_API_KEY", str(internal_key))
            except Exception:
                # Best-effort only.
                pass

            if APIClient is not None:
                try:
                    if getattr(APIClient, "defaults", None) is None:
                        APIClient.defaults = {}
                    APIClient.defaults.setdefault("HTTP_X_API_KEY", str(internal_key))
                except Exception:
                    pass

        # Call super().setUp() if present.
        super_setUp = getattr(super(), "setUp", None)
        if callable(super_setUp):
            super_setUp()
        # Also ensure the instance test client (self.client) has the header
        try:
            internal_key = os.environ.get("INTERNAL_API_KEY") or getattr(settings, "INTERNAL_API_KEY", None)
            if internal_key and hasattr(self, "client"):
                try:
                    if getattr(self.client, "defaults", None) is None:
                        self.client.defaults = {}
                    self.client.defaults.setdefault("HTTP_X_API_KEY", str(internal_key))
                except Exception:
                    pass
        except Exception:
            pass
