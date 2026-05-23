"""
Custom exception handlers for F1 API.

Provides unified error responses with helpful upgrade and retry messages.
Especially handles rate limiting (429) with tier upgrade prompts.
"""
from rest_framework.views import exception_handler
from rest_framework.exceptions import Throttled
from rest_framework.response import Response


def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF.
    
    Wraps DRF's default handler and adds custom 429 (rate limit) response.
    All other exceptions use default formatting.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled):
        request = context.get("request")
        tier = "free"
        if request and hasattr(request, "user"):
            tier = getattr(request.user, "tier", "free")

        response = Response(
            {
                "error": "Rate limit exceeded",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "retry_after_seconds": int(exc.wait) if exc.wait else 1,
                "tier": tier,
                "upgrade_message": (
                    "Need higher limits? "
                    "Reply to your API key email to request an upgrade."
                ),
            },
            status=429,
        )
        if exc.wait:
            response["Retry-After"] = int(exc.wait)

    return response
