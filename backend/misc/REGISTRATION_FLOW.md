# F1 API — API Key Registration Flow

## Overview

The F1 API uses email-based API key registration with a 3-step verification flow. Keys are issued with tier-based rate limits and token bucket throttling.

---

## 3-Step Registration Flow

### Step 1: Request API Key (POST)

**Endpoint:** `POST /api/auth/register/`

**Request:**

```json
{
  "email": "user@example.com"
}
```

**Response:** `202 Accepted`

```json
{
  "message": "Verification email sent",
  "email": "user@example.com",
  "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending_verification"
}
```

**What happens:**

- Django creates an `APIKey` record with `is_active=False`
- Task `send_verification_email` is enqueued to `tier6_notifications` queue
- Email contains a clickable verification link: `https://f1api.example.com/api/auth/verify/{api_key_id}/`
- Response is returned immediately (async email delivery)

**Gotcha:** The key is **inactive** until Step 2. Any requests using this key will fail with `401 Unauthorized` during this period.

---

### Step 2: Verify Email (GET)

**Endpoint:** `GET /api/auth/verify/{api_key_id}/`

**Response:** `200 OK`

```json
{
  "message": "API key activated",
  "email": "user@example.com",
  "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
  "api_key": "9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b",
  "tier": "free",
  "status": "active"
}
```

**What happens:**

- Django sets `is_active=True` on the APIKey record
- Task `send_welcome_email` is enqueued to `tier6_notifications` queue
- Client receives the actual **API key UUID** for the first time

**Gotcha:** This GET link should not be bookmarked. It activates the key once. Subsequent opens return 400 (already active).

---

### Step 3: Receive Welcome Email

**Timing:** Arrives shortly after Step 2 completes

**Email Subject:** `Welcome! Your Free API Key is Active`

**Email Body:**

```
Your API key is now active and ready to use!

Tier: Free
Status: Active

Rate Limits (Token Bucket):
  Capacity: 60 tokens
  Refill rate: 0.5 tokens/second
  Daily cap: 5,000 requests

Endpoint Costs:
  Lightweight (schedule, standings): 1 token
  Standard (laps, pace, positions): 2 tokens
  Heavy (telemetry): 5-8 tokens

Example: A telemetry request costs 5 tokens. With 0.5 tokens/second refill,
you can make 1 telemetry request every 10 seconds at steady state.

Daily cap: Once you hit 5,000 requests in a 24-hour period, all requests
are blocked for the remainder of the day. Plan accordingly during peak usage.

To upgrade your tier, reply to this email or visit:
https://f1api.example.com/account/upgrade/

Happy analyzing!
- F1 API Team
```

**What happens:**

- Email is delivered asynchronously (typically within 30 seconds)
- Client can now begin making API requests using their key

---

## API Key Usage

### Request Format

All subsequent API calls must include the key:

```bash
curl -H "X-API-Key: 9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b" \
  https://f1api.example.com/api/races/2026/
```

### Response Headers

Every response includes rate limit information:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 48
X-RateLimit-Cost: 1
X-RateLimit-Reset: 1684944000
X-RateLimit-Daily-Cap: 5000
```

Meaning: You have 48 tokens remaining out of 60 capacity. This request cost 1 token. Your daily cap is 5000 requests, with no daily usage shown (see `/api/auth/me/` for daily stats).

### Rate Limit Exceeded Response

When you exceed rate limits (either bucket or daily cap):

```
HTTP 429 Too Many Requests

{
  "error": "Rate limit exceeded",
  "error_code": "RATE_LIMIT_EXCEEDED",
  "retry_after_seconds": 45,
  "tier": "free",
  "upgrade_message": "Upgrade to Standard tier for 300 tokens capacity and 50k daily requests"
}
```

Header: `Retry-After: 45`

**Recommendation:** Implement exponential backoff using the `Retry-After` header.

---

## Endpoint: Check My Status

### Get Current Rate Limit Status

**Endpoint:** `GET /api/auth/me/`

**Response:** `200 OK`

```json
{
  "email": "user@example.com",
  "tier": "free",
  "is_active": true,
  "created_at": "2026-05-23T10:30:00Z",
  "last_used_at": "2026-05-23T10:35:15Z",
  "total_requests": 127,
  "rate_limits": {
    "bucket_capacity": 60,
    "refill_rate": 0.5,
    "daily_cap": 5000,
    "tokens_remaining_now": 42,
    "daily_used_today": 127,
    "daily_remaining_today": 4873
  }
}
```

Use this endpoint to:

- Check available tokens before making expensive requests
- Track daily usage
- Decide whether to implement backoff logic

---

## Endpoint: Revoke Key

### Deactivate API Key

**Endpoint:** `POST /api/auth/revoke/`

**Request:** (no body required, uses current key)

**Response:** `200 OK`

```json
{
  "message": "API key revoked",
  "email": "user@example.com",
  "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "revoked"
}
```

**What happens:**

- Django sets `is_active=False`
- Task `send_key_revocation_email` is enqueued
- All subsequent requests with this key immediately fail with `401 Unauthorized`
- Revocation is permanent — you must request a new key to continue

---

## Gotchas & Edge Cases

### Verification Link Expiry

The verification link is valid for **30 minutes** only. If you don't click within that window, you must request a new key (Step 1 again). This is a security measure to prevent old links from being exploited.

### Multiple Keys Per Email

You can request a new key even if you already have an active one. The old key remains valid. To deactivate it, use the `/api/auth/revoke/` endpoint explicitly.

### Rate Limits Apply Per Key

If you have 3 active keys, each has its own independent rate limit bucket. A burst on one key does not affect the others.

### Daily Cap Resets at Midnight UTC

The daily request counter resets at `2026-05-24T00:00:00Z`, regardless of your timezone. Plan accordingly if you have burst traffic patterns.

### Internal Tier Per-IP Throttling

The `internal` tier (reserved for F1 API infrastructure) includes an additional **per-IP bucket** on top of the global key bucket. Both must pass for a request to succeed:

- IP bucket: 200 capacity, 2.0 tokens/sec
- Key bucket: 500 capacity, 5.0 tokens/sec (internal tier)

This means two different IPs using the same internal key have independent IP buckets but share the same key bucket. Coordination is required if you operate multiple services behind the internal key.

---

## Common Workflows

### Workflow 1: Register & Start Using

```bash
# Step 1: Request
curl -X POST https://f1api.example.com/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email": "me@example.com"}'

# Response: 202, check your email

# Step 2: Click link in email or use the api_key_id:
curl https://f1api.example.com/api/auth/verify/550e8400-e29b-41d4-a716-446655440000/

# Response: 200, contains your api_key

# Step 3: Make requests
curl -H "X-API-Key: 9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b" \
  https://f1api.example.com/api/races/2026/
```

### Workflow 2: Check Status Before Heavy Request

```bash
# Check if you have enough tokens
curl -H "X-API-Key: 9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b" \
  https://f1api.example.com/api/auth/me/

# Response shows: tokens_remaining_now: 42
# Telemetry costs 5 tokens, so you can make 8 telemetry requests

curl -H "X-API-Key: 9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b" \
  https://f1api.example.com/api/races/2026/4/telemetry/?driver=VER
```

### Workflow 3: Implement Exponential Backoff

```python
import time
import requests

key = "9f86d081-884c-11d3-9a3c-4a5c-8e9f-9d7e5e8d9c5b"

for attempt in range(5):
    response = requests.get(
        "https://f1api.example.com/api/races/2026/4/telemetry/",
        headers={"X-API-Key": key}
    )

    if response.status_code == 200:
        print("Success:", response.json())
        break
    elif response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        print(f"Rate limited. Waiting {retry_after} seconds...")
        time.sleep(retry_after)
    else:
        print("Error:", response.status_code)
        break
```

---

## Support & Upgrade

- **Questions?** Email support@f1api.example.com
- **Need more requests?** Upgrade from Free to Standard (50k daily) or Premium (500k daily) at https://f1api.example.com/account/upgrade/
- **Integrating at scale?** Contact us for the Internal tier with per-IP throttling and custom rate limits.

---

**Generated:** May 23, 2026  
**F1 API Documentation**
