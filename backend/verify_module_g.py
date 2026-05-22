#!/usr/bin/env python
"""Verify Module G middleware audit."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
sys.path.insert(0, os.getcwd())
django.setup()

# Test 1: Import middleware
try:
    from api.middleware.csrf_exempt import CsrfExemptSessionMiddleware
    print("✓ CsrfExemptSessionMiddleware imported successfully")
except Exception as e:
    print(f"✗ Failed to import middleware: {e}")
    sys.exit(1)

# Test 2: Verify middleware is in settings
try:
    from django.conf import settings
    middleware_list = settings.MIDDLEWARE
    if 'api.middleware.csrf_exempt.CsrfExemptSessionMiddleware' in middleware_list:
        print("✓ CsrfExemptSessionMiddleware registered in MIDDLEWARE")
    else:
        print("✗ CsrfExemptSessionMiddleware NOT in MIDDLEWARE list")
        sys.exit(1)
except Exception as e:
    print(f"✗ Failed to check middleware in settings: {e}")
    sys.exit(1)

# Test 3: Verify middleware order (should be before CsrfViewMiddleware)
try:
    csrf_exempt_idx = middleware_list.index('api.middleware.csrf_exempt.CsrfExemptSessionMiddleware')
    csrf_view_idx = middleware_list.index('django.middleware.csrf.CsrfViewMiddleware')
    
    if csrf_exempt_idx < csrf_view_idx:
        print(f"✓ Middleware order correct: CsrfExemptSessionMiddleware (index {csrf_exempt_idx}) before CsrfViewMiddleware (index {csrf_view_idx})")
    else:
        print(f"✗ Middleware order incorrect: CsrfExemptSessionMiddleware should be before CsrfViewMiddleware")
        sys.exit(1)
except ValueError as e:
    print(f"✗ Middleware not found in list: {e}")
    sys.exit(1)

# Test 4: Instantiate middleware and test logic
try:
    from django.test import RequestFactory
    
    # Create a Django RequestFactory for proper request objects
    factory = RequestFactory()
    
    # Create a mock get_response
    def mock_get_response(request):
        from django.http import HttpResponse
        return HttpResponse()
    
    # Create middleware instance
    middleware = CsrfExemptSessionMiddleware(mock_get_response)
    print("✓ Middleware instantiated successfully")
    
    # Test API request (should set csrf_processing_done)
    api_request = factory.get('/api/auth/register/')
    middleware(api_request)
    
    if hasattr(api_request, 'csrf_processing_done') and api_request.csrf_processing_done is True:
        print("✓ API request correctly marked with csrf_processing_done=True")
    else:
        print("✗ API request NOT marked with csrf_processing_done")
        sys.exit(1)
    
    # Test non-API request (should NOT set csrf_processing_done)
    admin_request = factory.get('/admin/')
    middleware(admin_request)
    
    # For non-API requests, csrf_processing_done should NOT be set by our middleware
    # (It might be set by other middleware, but not by this one)
    if not (hasattr(admin_request, 'csrf_processing_done') and admin_request.csrf_processing_done is True):
        print("✓ Non-API request NOT marked by CsrfExemptSessionMiddleware (retains CSRF protection)")
    else:
        print("✗ Non-API request incorrectly marked by CsrfExemptSessionMiddleware")
        sys.exit(1)
    
except Exception as e:
    print(f"✗ Middleware logic test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✅ Module G middleware audit verified successfully!")
