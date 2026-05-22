"""
Token bucket throttling using Redis + Lua for efficient rate limiting.

Per-tier rate limits:
- free: 100 requests per minute
- basic: 500 requests per minute
- pro: 2000 requests per minute
- enterprise: 10000 requests per minute (effectively unlimited)
"""

from rest_framework.throttling import BaseThrottle
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from django.core.cache import caches
from django.conf import settings
from typing import Optional, Tuple
import hashlib
import time

from api.models import APIKey


# Lua script for token bucket algorithm
# Atomically decrements tokens and returns (tokens_remaining, refill_rate)
RATE_LIMIT_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])  -- bucket capacity (max tokens)
local refill_rate = tonumber(ARGV[2])  -- tokens per second
local now = tonumber(ARGV[3])  -- current timestamp
local tokens_needed = tonumber(ARGV[4])  -- tokens for this request (usually 1)

-- Get current state: {last_refill_time, tokens}
local state = redis.call('GET', key)
local last_refill, tokens

if state then
    -- Parse stored state (format: "timestamp:tokens")
    local parts = {}
    for part in string.gmatch(state, "[^:]+") do
        table.insert(parts, part)
    end
    last_refill = tonumber(parts[1])
    tokens = tonumber(parts[2])
else
    -- First request: bucket is full
    last_refill = now
    tokens = capacity
end

-- Calculate refill: time_passed * refill_rate, capped at capacity
local time_passed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + (time_passed * refill_rate))

-- Try to consume tokens
local allowed = tokens >= tokens_needed
if allowed then
    tokens = tokens - tokens_needed
end

-- Save new state
local new_state = now .. ":" .. tokens
redis.call('SET', key, new_state, 'EX', capacity)  -- TTL = bucket capacity (in seconds)

-- Return: allowed (1/0), tokens_remaining, refill_rate
return {allowed and 1 or 0, math.floor(tokens), refill_rate}
"""


class APIKeyThrottle(BaseThrottle):
    """
    Token bucket throttler for API key-authenticated requests.
    
    Tier-based rate limits (requests per minute):
    - free: 100 (1.67 req/sec)
    - basic: 500 (8.33 req/sec)
    - pro: 2000 (33.33 req/sec)
    - enterprise: 10000 (166.67 req/sec)
    
    Falls back to per-endpoint throttling for unauthenticated requests.
    """
    
    # Requests per minute per tier
    TIER_LIMITS = {
        'free': 100,
        'basic': 500,
        'pro': 2000,
        'enterprise': 10000,
    }
    
    cache = caches['rate_limit']
    scope = 'api_key_throttle'
    
    def get_cache_key(self, request: Request, view) -> Optional[str]:
        """
        Generate cache key for rate limiting.
        
        Uses API key if authenticated, otherwise uses IP address + endpoint.
        """
        # Check if request is authenticated with an API key
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            # Rate limit by API key + endpoint
            endpoint = view.__class__.__name__ if view else 'unknown'
            return f'throttle:{request.auth.key}:{endpoint}'
        
        # Unauthenticated: rate limit by IP + endpoint
        if request.META.get('HTTP_X_FORWARDED_FOR'):
            ip = request.META.get('HTTP_X_FORWARDED_FOR').split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '0.0.0.0')
        
        endpoint = view.__class__.__name__ if view else 'unknown'
        return f'throttle:ip:{ip}:{endpoint}'
    
    def allow_request(self, request: Request, view) -> bool:
        """
        Check if request should be allowed based on rate limit.
        
        Uses Redis Lua script for atomic token bucket decrements.
        """
        cache_key = self.get_cache_key(request, view)
        if not cache_key:
            # No cache key: allow request
            return True
        
        # Determine tier and rate limit
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            tier = request.auth.tier
            requests_per_minute = self.TIER_LIMITS.get(tier, 100)
        else:
            # Unauthenticated: use 'free' tier limit
            requests_per_minute = self.TIER_LIMITS['free']
        
        # Convert to tokens per second
        refill_rate = requests_per_minute / 60.0
        bucket_capacity = requests_per_minute  # Allow burst up to 1 minute of requests
        now = time.time()
        
        try:
            # Execute Lua script for token bucket
            result = self.cache.client.get_client().eval(
                RATE_LIMIT_LUA_SCRIPT,
                1,  # number of keys
                cache_key,  # KEYS[1]
                bucket_capacity,  # ARGV[1]
                refill_rate,  # ARGV[2]
                now,  # ARGV[3]
                1,  # ARGV[4] tokens_needed
            )
            
            allowed = result[0] == 1
            tokens_remaining = result[1]
            
            # Store remaining tokens on request for response headers
            request.rate_limit_remaining = tokens_remaining
            request.rate_limit_reset = int(now) + int(bucket_capacity)  # Reset after bucket TTL
            
            return allowed
        except Exception:
            # Redis error: allow request (fail open)
            return True
    
    def throttle_success(self, request: Request, view) -> bool:
        """Called after allow_request returns True."""
        # Store rate limit info on request for response headers
        if not hasattr(request, 'rate_limit_remaining'):
            request.rate_limit_remaining = -1
        if not hasattr(request, 'rate_limit_reset'):
            request.rate_limit_reset = -1
        return True
    
    def throttle_failure(self, request: Request, view):
        """Called after allow_request returns False."""
        # Calculate wait time (simplified: assume 1 token needed, so ~60/rate_limit seconds)
        if hasattr(request, 'auth') and isinstance(request.auth, APIKey):
            tier = request.auth.tier
            requests_per_minute = self.TIER_LIMITS.get(tier, 100)
        else:
            requests_per_minute = self.TIER_LIMITS['free']
        
        wait_time = 60.0 / requests_per_minute  # Seconds until next request allowed
        
        raise Throttled(wait=wait_time, detail=f'Request rate limit exceeded. Retry after {int(wait_time)} seconds.')
