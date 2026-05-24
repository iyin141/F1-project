"""
API Key authentication for tier-based rate limiting.
Reads key from X-API-Key header or ?api_key= query parameter.
"""
import logging
import uuid
from typing import Optional, Tuple

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


class APIKeyAuthentication(BaseAuthentication):
    """
    Authenticate requests using X-API-Key header or ?api_key= query param.
    Returns (api_key, api_key) so request.user and request.auth both work.
    """

    def authenticate(self, request):
        # Exempt paths — no key required
        path = request.path.rstrip("/")
        if any(path.startswith(p) for p in SKIP_AUTH_PREFIXES):
            return None

        # Extract key from header or query param
        key = (
            request.headers.get("X-API-Key")
            or request.query_params.get("api_key")
        )

        if not key:
            raise AuthenticationFailed(
                "API key required. Include X-API-Key header or ?api_key= parameter."
            )

        # Validate UUID format
        try:
            uuid.UUID(str(key))
        except ValueError:
            raise AuthenticationFailed("Invalid API key format.")

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
                api_key_obj = APIKey.objects.get(key=key, is_active=True)
            except APIKey.DoesNotExist:
                raise AuthenticationFailed("Invalid or inactive API key.")

            # Backfill cache
            try:
                cache = caches["default"]
                cache.set(f"apikey:{key}", api_key_obj, timeout=300)
            except Exception as exc:
                logger.warning("event=auth_cache_set_failed error=%s", exc)

        # Update last used
        try:
            api_key_obj.mark_used()
        except Exception:
            pass

        return (AnonymousUser(), api_key_obj)

    def authenticate_header(self, request):
        return "X-API-Key"
