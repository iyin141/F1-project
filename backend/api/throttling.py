"""
Token Bucket Rate Limiting for F1 API.

Implements distributed token bucket algorithm with per-tier configurations,
per-endpoint costs, daily caps, and per-IP buckets for internal keys.

All state stored in Redis 4 (rate_limit cache) using atomic Lua script.
No distributed locks needed — Lua execution is atomic in Redis.

Tier configurations:
  free:       60 capacity, 0.5 tokens/sec, 5k daily cap
  standard:   300 capacity, 1.67 tokens/sec, 50k daily cap
  premium:    2000 capacity, 8.33 tokens/sec, 500k daily cap
  internal:   500 capacity, 5 tokens/sec, unlimited daily cap + per-IP bucket
"""

import time
import hashlib
from typing import Tuple
from django.core.cache import caches
from rest_framework.throttling import BaseThrottle

# Token cost per endpoint type.
# Set request.endpoint_type in each view to use per-endpoint costs.
ENDPOINT_COSTS = {
    "schedule":           1,
    "standings":          1,
    "career":             1,
    "race_detail":        1,
    "race_results":       1,
    "qualifying":         1,
    "weather":            1,
    "incidents":          1,
    "laps":               2,
    "pace":               2,
    "stints":             2,
    "positions":          2,
    "pit_stops":          2,
    "drs":                2,
    "track_status":       2,
    "full_session":       3,
    "telemetry":          5,
    "telemetry_overlay":  8,
}

# Tier configs — capacity, refill tokens/sec, daily cap (None = unlimited)
TIER_CONFIGS = {
    "free":     {"capacity": 60,   "refill": 0.5,  "daily_cap": 5_000},
    "standard": {"capacity": 300,  "refill": 1.67, "daily_cap": 50_000},
    "premium":  {"capacity": 2000, "refill": 8.33, "daily_cap": 500_000},
    "internal": {"capacity": 500,  "refill": 5.0,  "daily_cap": None},
}

# Per-IP bucket config (applied on top of internal key)
IP_CONFIG = {"capacity": 200, "refill": 2.0}

# Atomic Lua script — executed in Redis 4, no race conditions
TOKEN_BUCKET_LUA = """
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now         = tonumber(ARGV[3])
local cost        = tonumber(ARGV[4])

local last       = tonumber(redis.call('GET', KEYS[2])) or now
local tokens     = tonumber(redis.call('GET', KEYS[1])) or capacity
local elapsed    = math.max(0, now - last)
local new_tokens = math.min(capacity, tokens + (elapsed * refill_rate))

if new_tokens < cost then
    local wait = math.ceil((cost - new_tokens) / refill_rate)
    return {0, wait, math.floor(new_tokens)}
end

local remaining = new_tokens - cost
redis.call('SET', KEYS[1], remaining)
redis.call('SET', KEYS[2], now)
redis.call('EXPIRE', KEYS[1], 3600)
redis.call('EXPIRE', KEYS[2], 3600)
return {1, 0, math.floor(remaining)}
"""


def _get_redis():
    """Raw Redis client from Redis 4 (rate_limit cache)."""
    return caches["rate_limit"].client.get_client()


def _run_token_bucket(
    tokens_key: str,
    last_key: str,
    capacity: float,
    refill_rate: float,
    cost: int,
) -> Tuple[bool, int, int]:
    """
    Execute atomic token bucket check.
    
    Args:
        tokens_key: Redis key for current token count
        last_key: Redis key for last update timestamp
        capacity: Bucket capacity (max tokens)
        refill_rate: Tokens per second
        cost: Tokens to consume this request
    
    Returns:
        (allowed, wait_seconds, tokens_remaining)
    """
    redis = _get_redis()
    result = redis.eval(
        TOKEN_BUCKET_LUA,
        2,
        tokens_key,
        last_key,
        capacity,
        refill_rate,
        time.time(),
        cost,
    )
    return bool(result[0]), int(result[1]), int(result[2])


def _check_daily_cap(api_key_str: str, daily_cap) -> Tuple[bool, int]:
    """
    Check if today's usage is under daily cap.
    
    Returns (under_cap, count).
    Increments daily counter in Redis 4 if under cap.
    """
    if daily_cap is None:
        return True, 0
    
    from datetime import date
    redis = _get_redis()
    day_key = f"tb:{api_key_str}:day:{date.today().isoformat()}"
    count = int(redis.get(day_key) or 0)
    
    if count >= daily_cap:
        return False, count
    
    redis.incr(day_key)
    redis.expire(day_key, 86400)
    return True, count + 1


def get_endpoint_cost(request) -> int:
    """
    Derive token cost from request.
    
    Preference order:
    1. request.endpoint_type (set by view)
    2. ENDPOINT_COSTS lookup
    3. URL path inference
    4. Default: 1
    """
    endpoint_type = getattr(request, "endpoint_type", None)
    if endpoint_type:
        return ENDPOINT_COSTS.get(endpoint_type, 1)
    
    path = request.path
    if "telemetry/overlay" in path:
        return ENDPOINT_COSTS.get("telemetry_overlay", 1)
    if "telemetry" in path:
        return ENDPOINT_COSTS.get("telemetry", 1)
    if any(x in path for x in [
        "laps", "pace", "stints", "positions",
        "pit-stops", "drs", "track-status"
    ]):
        return 2
    return 1


class APIKeyThrottle(BaseThrottle):
    """
    Token bucket throttle per API key.
    
    For internal tier: also applies per-IP bucket (independent per IP).
    Both buckets must pass (tokens AND IP quota).
    
    Stores all state in Redis 4 (rate_limit cache) with atomic updates.
    """

    def allow_request(self, request, view):
        api_key = getattr(request, "user", None)
        if api_key is None or not hasattr(api_key, "key"):
            return False

        key_str = str(api_key.key)
        tier = getattr(api_key, "tier", "free")
        config = TIER_CONFIGS.get(tier, TIER_CONFIGS["free"])
        cost = get_endpoint_cost(request)

        # --- Daily cap check ---
        under_cap, daily_count = _check_daily_cap(key_str, config["daily_cap"])
        if not under_cap:
            self._wait = 86400
            self._remaining = 0
            self._daily_exceeded = True
            return False
        self._daily_exceeded = False

        # --- Per-key token bucket ---
        allowed, wait, remaining = _run_token_bucket(
            tokens_key=f"tb:{key_str}:tokens",
            last_key=f"tb:{key_str}:last",
            capacity=config["capacity"],
            refill_rate=config["refill"],
            cost=cost,
        )
        self._wait = wait
        self._remaining = remaining
        self._cost = cost
        self._limit = config["capacity"]

        if not allowed:
            return False

        # --- Internal key: per-IP bucket on top ---
        if tier == "internal":
            ip = self._get_ip(request)
            # SHA256-hash IP — never store raw IPs
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
            ip_allowed, ip_wait, ip_remaining = _run_token_bucket(
                tokens_key=f"tb:ip:{ip_hash}:tokens",
                last_key=f"tb:ip:{ip_hash}:last",
                capacity=IP_CONFIG["capacity"],
                refill_rate=IP_CONFIG["refill"],
                cost=1,  # IP bucket always costs 1 regardless of endpoint
            )
            if not ip_allowed:
                self._wait = ip_wait
                self._remaining = ip_remaining
                return False

        # --- Store for response headers ---
        request._tb_remaining = remaining
        request._tb_reset = int(time.time()) + (wait if wait else 0)
        request._tb_limit = config["capacity"]
        request._tb_cost = cost
        request._tb_daily_cap = config["daily_cap"]
        return True

    def wait(self):
        """Return wait time in seconds for retry-after header."""
        return getattr(self, "_wait", 1)

    @staticmethod
    def _get_ip(request) -> str:
        """
        Extract client IP from request.
        
        Respects X-Forwarded-For header from Nginx/reverse proxy.
        Falls back to REMOTE_ADDR.
        """
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")
