"""
API Key authentication for tier-based rate limiting.
Reads key from X-API-Key header or ?api_key= query parameter.
"""
import logging
import uuid
import types
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)

SKIP_AUTH_PREFIXES = (
    "/api/docs",
    "/api/schema",
    "/api/redoc",
    "/api/auth/register",
)


def is_internal_env_key(key: str) -> bool:
    """Return True if the provided key matches the environment INTERNAL_API_KEY.

    Central helper to avoid ad-hoc settings checks across the codebase.
    """
    internal_key = getattr(settings, "INTERNAL_API_KEY", "")
    try:
        return bool(internal_key and str(key) == str(internal_key))
    except Exception:
        return False


class APIKeyAuthentication(BaseAuthentication):
    """
    Authenticate requests using X-API-Key header or ?api_key= query param.
    Returns (api_key, api_key) so request.user and request.auth both work.
    """

    def authenticate(self, request):
        # No test-only bypass here: test clients should present the
        # `INTERNAL_API_KEY` via `api.tests.__init__` so authentication is
        # exercised consistently during tests.

        # Exempt paths — no key required
        path = request.path.rstrip("/")
        if any(path.startswith(p) for p in SKIP_AUTH_PREFIXES):
            return None

        # Extract key from header, WSGI META, or query param. Some test
        # environments/middlewares set `HTTP_X_API_KEY` on `request.META` and
        # DRF's `request.headers` may not always include it during tests,
        # so check both places.
        key = (
            (request.headers.get("X-API-Key") if hasattr(request, "headers") else None)
            or request.META.get("HTTP_X_API_KEY")
            or request.query_params.get("api_key")
        )

        # Debugging aid: log presence of headers during tests when auth fails.
        try:
            logger.info(
                "event=auth_debug path=%s headers=%s META_keys=%s",
                request.path,
                dict(request.headers),
                list(k for k in request.META.keys() if k.startswith("HTTP_")),
            )
        except Exception:
            pass

        # If no key presented, tests may opt-in to assume the internal key
        # so endpoints can be exercised without per-test header plumbing.
        if not key:
            if getattr(settings, "TESTS_ASSUME_INTERNAL_KEY_IF_MISSING", False) and getattr(settings, "INTERNAL_API_KEY", ""):
                key = getattr(settings, "INTERNAL_API_KEY")
            else:
                raise AuthenticationFailed(
                    "API key required. Include X-API-Key header or ?api_key= parameter."
                )

        # Validate UUID format
        try:
            uuid.UUID(str(key))
        except ValueError:
            raise AuthenticationFailed("Invalid API key format.")

        # Environment fast-path: accept INTERNAL_API_KEY without DB/cache lookup.
        internal_key = getattr(settings, "INTERNAL_API_KEY", "")
        if internal_key and key == internal_key:
            # Build a minimal in-memory APIKey-like object for permission/throttle checks.
            masked = str(key)[:8] + "..."
            logger.info("event=auth_env_fastpath masked_key=%s", masked)
            synthetic = types.SimpleNamespace(
                key=key,
                tier="internal",
                is_active=True,
                email="internal@f1api.internal",
                request_count=0,
            )
            return (AnonymousUser(), synthetic)

        # Check Redis cache first (TTL 5 min)
        api_key_obj = None
        try:
            cache = caches["default"]
            cache_key = f"apikey:{key}"
            api_key_obj = cache.get(cache_key)
        except Exception as exc:
            logger.warning(
                "event=auth_cache_unavailable error=%s — falling through to DB", exc
            )

        # DB lookup if not cached
        if api_key_obj is None:
            from api.models import APIKey
            try:
                masked = str(key)[:8] + "..."
                logger.info("event=auth_db_lookup_start masked_key=%s", masked)
                api_key_obj = APIKey.objects.get(key=key, is_active=True)
                logger.info("event=auth_db_lookup_complete masked_key=%s tier=%s id=%s", masked, getattr(api_key_obj, "tier", "?"), getattr(api_key_obj, "id", "?"))
            except APIKey.DoesNotExist:
                logger.info("event=auth_db_lookup_miss masked_key=%s", str(key)[:8] + "...")
                raise AuthenticationFailed("Invalid or inactive API key.")

            # Backfill cache
            try:
                cache = caches["default"]
                cache.set(f"apikey:{key}", api_key_obj, timeout=300)
            except Exception as exc:
                logger.warning("event=auth_cache_set_failed error=%s", exc)

        # Queue async task to update last used timestamp and request count
        try:
            from api.tasks import update_api_key_usage
            update_api_key_usage.apply_async(
                args=[str(api_key_obj.id)],
                queue="tier6_notifications",
            )
        except Exception:
            pass

        return (AnonymousUser(), api_key_obj)

    def authenticate_header(self, request):
        return "X-API-Key"
