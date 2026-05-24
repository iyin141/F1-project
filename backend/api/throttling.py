"""
Token bucket rate limiting for the F1 API.

Two throttle classes:
  APIKeyThrottle      — per API key token bucket, with endpoint costs.
                        Internal tier also gets a per-IP bucket on top.
  RegistrationThrottle — IP-based only, for register/verify endpoints.
                         No API key required.

Fail-open design: if Redis 4 is unavailable, requests are allowed through
and a WARNING is logged. Never deny requests because Redis is down.
"""
import hashlib
import logging
import time
from datetime import date

from django.core.cache import caches
from rest_framework.throttling import BaseThrottle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exempt and registration paths
# ---------------------------------------------------------------------------

THROTTLE_EXEMPT_PREFIXES = ("/api/docs", "/api/schema", "/api/redoc")
REGISTRATION_PREFIXES = ("/api/auth/register", "/api/auth/verify")

# ---------------------------------------------------------------------------
# Endpoint token costs
# ---------------------------------------------------------------------------

ENDPOINT_COSTS = {
    "schedule":          1,
    "standings":         1,
    "career":            1,
    "race_detail":       1,
    "race_results":      1,
    "qualifying":        1,
    "weather":           1,
    "incidents":         1,
    "laps":              2,
    "pace":              2,
    "stints":            2,
    "positions":         2,
    "pit_stops":         2,
    "drs":               2,
    "track_status":      2,
    "full_session":      3,
    "telemetry":         5,
    "telemetry_overlay": 5,
}

# ---------------------------------------------------------------------------
# Tier configs
# ---------------------------------------------------------------------------

TIER_CONFIGS = {
    "free":     {"capacity": 60,   "refill": 0.5,  "daily_cap": 5_000},
    "standard": {"capacity": 300,  "refill": 1.67, "daily_cap": 50_000},
    "premium":  {"capacity": 2000, "refill": 8.33, "daily_cap": 500_000},
    "internal": {"capacity": 500,  "refill": 5.0,  "daily_cap": None},
}

# Per-IP config applied on top of internal key
IP_CONFIG = {"capacity": 200, "refill": 2.0}

# ---------------------------------------------------------------------------
# Atomic Lua script — runs in Redis 4, no race conditions
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _get_redis():
    """
    Returns raw Redis 4 client.
    Returns None and logs WARNING if unavailable — callers must handle None.
    """
    try:
        return caches["rate_limit"].client.get_client()
    except Exception as exc:
        logger.warning(
            "event=rate_limit_redis_unavailable error=%s — failing open", exc
        )
        return None


def _run_token_bucket(
    tokens_key: str,
    last_key: str,
    capacity: float,
    refill_rate: float,
    cost: int,
) -> tuple:
    """
    Execute atomic token bucket via Lua script.
    Returns (allowed: bool, wait_seconds: int, remaining: int).
    Fails open if Redis unavailable.
    """
    redis = _get_redis()
    if redis is None:
        return True, 0, int(capacity)

    try:
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
    except Exception as exc:
        logger.warning(
            "event=token_bucket_error key=%s error=%s — failing open",
            tokens_key, exc
        )
        return True, 0, int(capacity)


def _check_daily_cap(api_key_str: str, daily_cap) -> tuple:
    """
    Returns (under_cap: bool, count: int).
    Increments daily counter. Fails open if Redis unavailable.
    """
    if daily_cap is None:
        return True, 0

    redis = _get_redis()
    if redis is None:
        return True, 0

    try:
        day_key = f"tb:{api_key_str}:day:{date.today().isoformat()}"
        count = int(redis.get(day_key) or 0)
        if count >= daily_cap:
            return False, count
        redis.incr(day_key)
        redis.expire(day_key, 86400)
        return True, count + 1
    except Exception as exc:
        logger.warning(
            "event=daily_cap_error key=%s error=%s — failing open",
            api_key_str, exc
        )
        return True, 0


def get_endpoint_cost(request) -> int:
    """
    Returns token cost for this request.
    Reads request.endpoint_type if set by the view (preferred).
    Falls back to URL path inference.
    """
    endpoint_type = getattr(request, "endpoint_type", None)
    if endpoint_type:
        return ENDPOINT_COSTS.get(endpoint_type, 1)

    path = request.path
    if "telemetry/overlay" in path:
        return ENDPOINT_COSTS["telemetry_overlay"]
    if "telemetry" in path:
        return ENDPOINT_COSTS["telemetry"]
    if any(x in path for x in [
        "laps", "pace", "stints", "positions",
        "pit-stops", "drs", "track-status",
    ]):
        return 2
    if "full-session" in path:
        return 3
    return 1


def _get_ip(request) -> str:
    """Real IP, respecting X-Forwarded-For from Nginx."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _hash_ip(ip: str) -> str:
    """SHA256-hash IP address — never store raw IPs in Redis."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# APIKeyThrottle
# ---------------------------------------------------------------------------


class APIKeyThrottle(BaseThrottle):
    """
    Token bucket throttle per API key.
    Internal tier also gets an independent per-IP bucket.
    Exempt paths bypass throttling entirely.
    Registration paths are handled by RegistrationThrottle, not this class.
    Fails open if Redis 4 is unavailable.
    """

    def allow_request(self, request, view):
        # Exempt paths — no throttling
        path = request.path.rstrip("/")
        if any(path.startswith(p) for p in THROTTLE_EXEMPT_PREFIXES):
            return True

        # Registration paths — handled by RegistrationThrottle
        if any(path.startswith(p) for p in REGISTRATION_PREFIXES):
            return True

        api_key = getattr(request, "auth", None)
        if api_key is None or not hasattr(api_key, "key"):
            # No key — auth layer will handle the 401
            return True

        key_str = str(api_key.key)
        tier = getattr(api_key, "tier", "free")
        config = TIER_CONFIGS.get(tier, TIER_CONFIGS["free"])
        cost = get_endpoint_cost(request)

        # Daily cap check
        under_cap, daily_count = _check_daily_cap(key_str, config["daily_cap"])
        if not under_cap:
            self._wait = 86400
            self._remaining = 0
            self._limit = config["capacity"]
            self._cost = cost
            self._daily_exceeded = True
            return False

        self._daily_exceeded = False

        # Per-key token bucket
        allowed, wait, remaining = _run_token_bucket(
            tokens_key=f"tb:{key_str}:tokens",
            last_key=f"tb:{key_str}:last",
            capacity=config["capacity"],
            refill_rate=config["refill"],
            cost=cost,
        )
        self._wait = wait
        self._remaining = remaining
        self._limit = config["capacity"]
        self._cost = cost

        if not allowed:
            return False

        # Internal key: additional per-IP bucket (independent per IP)
        if tier == "internal":
            ip = _get_ip(request)
            ip_hash = _hash_ip(ip)
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

        # Store for response headers
        request._tb_remaining = remaining
        request._tb_reset = int(time.time()) + (wait if wait else 0)
        request._tb_limit = config["capacity"]
        request._tb_cost = cost
        request._tb_daily_cap = config["daily_cap"]
        return True

    def wait(self):
        return getattr(self, "_wait", 1)


# ---------------------------------------------------------------------------
# RegistrationThrottle
# ---------------------------------------------------------------------------


class RegistrationThrottle(BaseThrottle):
    """
    IP-based token bucket for registration endpoints only.
    No API key involved. 5 attempts per hour per IP.
    Fails open if Redis 4 is unavailable.
    """

    CAPACITY = 5
    REFILL_RATE = 5 / 3600  # 5 per hour = ~0.00139 tokens/sec

    def allow_request(self, request, view):
        ip = _get_ip(request)
        ip_hash = _hash_ip(ip)

        allowed, wait, remaining = _run_token_bucket(
            tokens_key=f"tb:reg:{ip_hash}:tokens",
            last_key=f"tb:reg:{ip_hash}:last",
            capacity=self.CAPACITY,
            refill_rate=self.REFILL_RATE,
            cost=1,
        )
        self._wait = wait
        self._remaining = remaining
        # Attach helpful debug headers to the request so responses and
        # exception handlers can expose X-RateLimit-* information.
        try:
            request._tb_remaining = remaining
            request._tb_reset = int(time.time()) + (wait if wait else 0)
            request._tb_limit = self.CAPACITY
            request._tb_cost = 1
            request._tb_daily_cap = None
        except Exception:
            # Be defensive — don't crash the throttle on attribute errors
            pass

        return allowed

    def wait(self):
        return getattr(self, "_wait", 3600)


# ---------------------------------------------------------------------------
# AdminEndpointThrottle
# ---------------------------------------------------------------------------


class AdminEndpointThrottle(BaseThrottle):
    """
    IP-based token bucket for admin endpoints only.
    3 attempts per hour per IP — prevents brute force on admin password.
    Fails open if Redis unavailable.
    """

    CAPACITY = 3
    REFILL_RATE = 3 / 3600  # 3 per hour

    def allow_request(self, request, view):
        ip = _get_ip(request)
        ip_hash = _hash_ip(ip)
        allowed, wait, remaining = _run_token_bucket(
            tokens_key=f"tb:admin:{ip_hash}:tokens",
            last_key=f"tb:admin:{ip_hash}:last",
            capacity=self.CAPACITY,
            refill_rate=self.REFILL_RATE,
            cost=1,
        )
        self._wait = wait
        return allowed

    def wait(self):
        return getattr(self, "_wait", 3600)

