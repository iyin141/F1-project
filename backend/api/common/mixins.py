"""
Response mixins for rate limiting headers and other common patterns.
"""

from rest_framework.response import Response


class RateLimitHeadersMixin:
    """Add token bucket headers to every API response."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(
            request, response, *args, **kwargs
        )
        if hasattr(request, "_tb_remaining"):
            response["X-RateLimit-Limit"]     = request._tb_limit
            response["X-RateLimit-Remaining"] = request._tb_remaining
            response["X-RateLimit-Reset"]     = request._tb_reset
            response["X-RateLimit-Cost"]      = request._tb_cost
            if getattr(request, "_tb_daily_cap", None):
                response["X-RateLimit-Daily-Cap"] = request._tb_daily_cap
        return response
