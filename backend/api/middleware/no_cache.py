"""
No-cache middleware/mixin — Phase 5: Ensure task status endpoints never cache.

Applies proper HTTP headers to prevent any caching of live status data.
"""
from django.utils.decorators import decorator_from_middleware
from django.middleware.common import CommonMiddleware


class NoCacheHeadersMiddleware:
    """
    Middleware to add no-cache headers to responses for certain URL patterns.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Apply no-cache headers to task status endpoints
        if "/tasks/" in request.path and "/status/" in request.path:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            response["X-Cache-Control"] = "none"
        
        return response


from rest_framework.response import Response
from rest_framework import status as http_status


class NoCacheResponseMixin:
    """
    Mixin for DRF views to add no-cache headers to responses.
    """
    
    def finalize_response(self, request, response, *args, **kwargs):
        """Override finalize_response to add no-cache headers."""
        response = super().finalize_response(request, response, *args, **kwargs)
        
        # Only apply to task status endpoints
        if "/tasks/" in request.path and "/status/" in request.path:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        
        return response
