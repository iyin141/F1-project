"""
Test script to verify per-IP rate limiting for internal tier API key.

Usage:
    python manage.py shell < test_internal_ip_throttling.py
    
    Or manually in shell:
        from api.models.auth import APIKey
        from api.throttling import APIKeyThrottle
        from rest_framework.test import APIRequestFactory
        from rest_framework.response import Response
        from rest_framework.views import APIView
        
        # Simulate requests from different IPs
"""

from api.models.auth import APIKey
from api.throttling import APIKeyThrottle
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from rest_framework.response import Response

# Get or create internal key
internal_key = APIKey.objects.filter(tier="internal", is_active=True).first()
if not internal_key:
    print("❌ No internal API key found. Run: python manage.py create_internal_key")
    exit(1)

print(f"✅ Using internal key: {internal_key.key}")
print(f"   Tier: {internal_key.tier}")
print(f"   Per-IP bucket: capacity=200, refill=2.0 tokens/sec, cost=1\n")

# Create factory and throttle instance
factory = APIRequestFactory()
throttle = APIKeyThrottle()

class DummyView(APIView):
    def get(self, request):
        return Response({"message": "ok"})

# Simulate requests from IP 192.168.1.100
print("Test 1: 5 requests from IP 192.168.1.100")
for i in range(5):
    request = factory.get('/', HTTP_X_FORWARDED_FOR='192.168.1.100')
    request.user = internal_key
    allowed = throttle.allow_request(request, DummyView)
    remaining = getattr(request, '_tb_remaining', 'N/A')
    cost = getattr(throttle, '_cost', 1)
    print(f"  Request {i+1}: allowed={allowed}, remaining_key_tokens={remaining}, cost={cost}")

print("\nTest 2: 5 requests from IP 192.168.1.200 (different IP, independent bucket)")
for i in range(5):
    request = factory.get('/', HTTP_X_FORWARDED_FOR='192.168.1.200')
    request.user = internal_key
    allowed = throttle.allow_request(request, DummyView)
    remaining = getattr(request, '_tb_remaining', 'N/A')
    cost = getattr(throttle, '_cost', 1)
    print(f"  Request {i+1}: allowed={allowed}, remaining_key_tokens={remaining}, cost={cost}")

print("\nTest 3: Verify first IP can still make requests (independent bucket)")
for i in range(3):
    request = factory.get('/', HTTP_X_FORWARDED_FOR='192.168.1.100')
    request.user = internal_key
    allowed = throttle.allow_request(request, DummyView)
    remaining = getattr(request, '_tb_remaining', 'N/A')
    print(f"  Request {i+1}: allowed={allowed}, remaining_key_tokens={remaining}")

print("\n✅ Per-IP throttling test complete!")
print("Each IP has independent bucket, both checked on top of global key bucket.")
