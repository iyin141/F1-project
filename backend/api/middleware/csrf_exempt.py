"""
Middleware for API route exemption from CSRF and session processing.

API routes (/api/*) don't need:
- CSRF protection (they use token-based auth via APIKey)
- Session state management (they're stateless)

Other routes (including /admin/) retain full CSRF and session processing.
"""


class CsrfExemptSessionMiddleware:
    """
    Custom middleware that exempts API routes from CSRF and session processing.
    
    Must run BEFORE CsrfViewMiddleware in MIDDLEWARE list.
    
    Behavior:
    - /api/* routes: csrf_processing_done=True (CSRF middleware skips these)
    - Other routes: Normal CSRF/session processing
    - /admin/: Retains full protection
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Check if this is an API route
        if request.path.startswith('/api/'):
            # Mark CSRF as already processed - CsrfViewMiddleware will skip this request
            request.csrf_processing_done = True
        
        response = self.get_response(request)
        return response
