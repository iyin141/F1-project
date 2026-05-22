"""
Response mixins for rate limiting headers and other common patterns.
"""

from rest_framework.response import Response
from rest_framework.request import Request
from typing import Optional


class RateLimitHeadersMixin:
    """
    Mixin to add rate limit headers to API responses.
    
    Adds standard rate limit headers:
    - X-RateLimit-Limit: maximum requests per minute
    - X-RateLimit-Remaining: requests remaining in current window
    - X-RateLimit-Reset: Unix timestamp when limit resets
    - Retry-After: seconds to wait if rate limited (429 responses)
    
    Requires authentication with APIKey for tier-based limits.
    Falls back to free tier limits for unauthenticated requests.
    """
    
    TIER_LIMITS = {
        'free': 100,
        'basic': 500,
        'pro': 2000,
        'enterprise': 10000,
    }
    
    def get_rate_limit_headers(self, request: Request) -> dict:
        """
        Get rate limit headers for the current request.
        
        Args:
            request: The incoming request
            
        Returns:
            Dictionary of rate limit headers
        """
        from api.models import APIKey
        
        # Determine rate limit tier
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            tier = request.auth.tier
            limit = self.TIER_LIMITS.get(tier, 100)
        else:
            # Unauthenticated: free tier
            limit = self.TIER_LIMITS['free']
        
        # Get remaining tokens from throttle (if available)
        remaining = getattr(request, 'rate_limit_remaining', limit)
        reset = getattr(request, 'rate_limit_reset', 0)
        
        return {
            'X-RateLimit-Limit': str(limit),
            'X-RateLimit-Remaining': str(max(0, remaining)),
            'X-RateLimit-Reset': str(int(reset)),
        }
    
    def finalize_response(self, request: Request, response: Response, *args, **kwargs) -> Response:
        """
        Add rate limit headers to response.
        
        Called by DRF after view method returns.
        """
        # Add rate limit headers to all responses
        for header, value in self.get_rate_limit_headers(request).items():
            response[header] = value
        
        # Add Retry-After for 429 (Too Many Requests)
        if response.status_code == 429:
            wait_time = getattr(request, 'throttle_wait_time', 60)
            response['Retry-After'] = str(int(wait_time))
        
        return response
