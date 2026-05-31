"""
Package initializer for `api.tests`.

This module runs early during Django test discovery for the
`backend.api.tests` package. It enforces test-safe email settings and
injects a default `X-API-Key` into Django's test client so existing
endpoint tests run without per-test modifications.

Keep this file minimal and defensive to avoid interfering with test
discovery when Django test settings are not yet configured.
"""
from __future__ import annotations

import os
import logging

_log = logging.getLogger("api.tests.bootstrap")

# Import Django settings if available; be defensive because test discovery
# may import this before settings are configured in rare cases.
try:
    from django.conf import settings
except Exception:
    settings = None


# Enforce test-safe email backend and clear any live Resend key as a
# safeguard in case environment leakage occurs.
if settings is not None:
    try:
        # Clear Resend credentials so tests do not make external HTTP calls.
        setattr(settings, "RESEND_API_KEY", "")
        setattr(settings, "ANYMAIL", {})
        setattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.locmem.EmailBackend")
    except Exception:
        # Best-effort only; avoid raising during discovery.
        pass


# Transitional bootstrap removed: tests must opt-in to the internal API key
# via `TestDefaultAPIKeyMixin` or per-test `APIRequestFactory` wrappers.

# Import-time confirmation so test discovery shows this module was imported.
# Use a plain print because logging may not be configured at import time.
try:
    print("api.tests imported; transitional bootstrap removed")
except Exception:
    pass
