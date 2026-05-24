"""
Custom exception handlers for F1 API.

Provides unified error responses with helpful upgrade and retry messages.
Especially handles rate limiting (429) with tier upgrade prompts.
"""
import logging

from rest_framework.views import exception_handler
from rest_framework.exceptions import Throttled
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def _apply_rate_limit_headers(response, request):
    """Copy token-bucket debugging headers into the response if present on request."""
    if not request:
        return
    try:
        if hasattr(request, "_tb_limit"):
            response["X-RateLimit-Limit"] = request._tb_limit
        if hasattr(request, "_tb_remaining"):
            response["X-RateLimit-Remaining"] = request._tb_remaining
        if hasattr(request, "_tb_reset"):
            response["X-RateLimit-Reset"] = request._tb_reset
        if hasattr(request, "_tb_cost"):
            response["X-RateLimit-Cost"] = request._tb_cost
        if getattr(request, "_tb_daily_cap", None) is not None:
            response["X-RateLimit-Daily-Cap"] = request._tb_daily_cap
    except Exception as exc:
        logger.warning("event=rate_limit_header_error error=%s", exc)


def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF.

    Extends DRF's default handler and provides a tailored 429 response for
    throttled requests. Registration endpoints produce a simplified 429
    payload suitable for end-users, while API clients get tier/upgrade info.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled):
        request = context.get("request")
        retry_after = int(exc.wait) if getattr(exc, "wait", None) else 1

        tier = "free"
        if request and hasattr(request, "user"):
            tier = getattr(request.user, "tier", "free")

        # Detect registration endpoints and return a user-friendly payload
        path = getattr(request, "path", "")
        is_registration = False
        if path:
            p = path.rstrip("/")
            if p.startswith("/api/auth/register") or p.startswith("/api/auth/verify"):
                is_registration = True

        if is_registration:
            payload = {
                "error": "Too many registration attempts",
                "error_code": "REGISTRATION_RATE_LIMIT_EXCEEDED",
                "retry_after_seconds": retry_after,
                "message": "Too many registration attempts from this IP. Please try again later.",
            }
        else:
            payload = {
                "error": "Rate limit exceeded",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "retry_after_seconds": retry_after,
                "tier": tier,
                "upgrade_message": (
                    "Need higher limits? Reply to your API key email to request an upgrade."
                ),
            }

        response = Response(payload, status=429)
        response["Retry-After"] = retry_after

        # Propagate token-bucket headers when available for observability
        _apply_rate_limit_headers(response, request)

        # Log throttling events for monitoring
        try:
            client_ip = None
            if request:
                client_ip = request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR")
            logger.info(
                "event=throttled path=%s ip=%s retry=%s tier=%s",
                path,
                client_ip,
                retry_after,
                tier,
            )
        except Exception:
            logger.exception("event=throttled_logging_error")

    return response
