"""
API key registration and lifecycle management endpoints.

Provides endpoints for:
- New API key registration (email verification required)
- Tier selection and upgrades
- API key renewal and revocation
"""

"""
Registration, verification, and API key management views.

Endpoints:
  POST /api/auth/register/          — submit email, receive key via email
  GET  /api/auth/verify/<id>/       — activate key from email link
  GET  /api/auth/me/                — check your key details and quota
  POST /api/auth/internal-key/      — generate internal key (admin only)
"""
import uuid
import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework import serializers
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiResponse

from api.auth import APIKeyAuthentication
from api.throttling import RegistrationThrottle, AdminEndpointThrottle
from api.models.auth import APIKey

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response serializers for Swagger schema generation
# ---------------------------------------------------------------------------

class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(
        help_text="Your email address. Your API key will be sent here."
    )


class RegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    email = serializers.EmailField()


class RegisterAPIView(APIView):
    """
    POST /api/auth/register/
    Body: {"email": "user@example.com"}
    Returns 202 immediately. API key delivered via email.
    Rate limited by IP — 5 attempts per hour.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = []
    throttle_classes = [AdminEndpointThrottle]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        request=RegisterRequestSerializer,
        responses={
            202: RegisterResponseSerializer,
            400: OpenApiResponse(description="Invalid email format"),
            429: OpenApiResponse(description="Too many registration attempts (5/hour per IP)"),
        },
        examples=[
            OpenApiExample(
                "Register example",
                value={"email": "developer@example.com"},
                request_only=True,
            )
        ],
        summary="Register for an API key",
        description=(
            "Submit your email to receive an API key. "
            "A verification link will be sent to your email. "
            "Click the link to activate your key. "
            "Rate limited to 5 attempts per hour per IP address."
        ),
    )
    def post(self, request):
        # Enforce internal-only access: accept INTERNAL_API_KEY fast-path or an APIKey with tier 'internal'
        try:
            header_key = request.headers.get("X-Api-Key") or request.META.get("HTTP_X_API_KEY")
        except Exception:
            header_key = None

        is_internal = False
        if getattr(settings, "INTERNAL_API_KEY", None) and header_key and str(header_key) == str(getattr(settings, "INTERNAL_API_KEY")):
            is_internal = True
        else:
            auth_obj = getattr(request, "auth", None)
            if auth_obj and getattr(auth_obj, "tier", None) == "internal":
                is_internal = True

        if not is_internal:
            return Response({"error": "Unauthorized", "error_code": "UNAUTHORIZED"}, status=401)

        # Use serializer for validation and normalization
        serializer = RegisterRequestSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as exc:
            return Response({"error": "Invalid email", "details": str(exc)}, status=400)

        email = serializer.validated_data["email"]

        # Optional fuzzy duplicate detection (requires rapidfuzz)
        try:
            from datetime import timedelta
            from django.utils import timezone
            try:
                from rapidfuzz import fuzz  # type: ignore
                has_rapidfuzz = True
            except Exception:
                has_rapidfuzz = False

            if has_rapidfuzz:
                cutoff = timezone.now() - timedelta(days=30)
                recent = APIKey.objects.filter(created_at__gte=cutoff).exclude(email__iexact=email).values_list("email", flat=True)[:1000]
                for other in recent:
                    try:
                        score = fuzz.token_sort_ratio(email, other.lower())
                    except Exception:
                        score = 0
                    if score >= 85:
                        logger.info("event=registration_fuzzy_detect email=%s similar=%s score=%s", email, other, score)
                        return Response(
                            {
                                "error": "A similar email address was recently registered.",
                                "similar_email": other,
                                "similarity_score": int(score),
                                "error_code": "SIMILAR_EMAIL_EXISTS",
                            },
                            status=409,
                        )
        except Exception:
            logger.exception("event=registration_fuzzy_check_failed email=%s", email)

        # Check for existing API key
        try:
            existing = APIKey.objects.filter(email__iexact=email).first()
            if existing:
                if not existing.is_active:
                    try:
                        existing.is_active = True
                        existing.save(update_fields=["is_active"])
                    except Exception:
                        logger.exception("event=reactivate_existing_failed email=%s", email)

                # Re-send API key email via TaskManager (best-effort)
                try:
                    from api.queue.manager import TaskManager
                    from api.tasks import send_api_key_email

                    task_key = f"email_api_key:{existing.id}"
                    verification_link = request.build_absolute_uri(f"/api/auth/verify/{existing.id}/")
                    TaskManager.enqueue(task_key, send_api_key_email, str(existing.id), existing.email, verification_link)
                except Exception:
                    logger.exception("event=registration_resend_failed email=%s", email)

                return Response(
                    {
                        "message": "API key already exists for this email.",
                        "email": existing.email,
                        "api_key": str(existing.key),
                        "tier": existing.tier,
                    },
                    status=200,
                )
        except Exception:
            logger.exception("event=registration_existing_lookup_failed email=%s", email)

        # Create new API key and enqueue email task
        try:
            api_key = APIKey.objects.create(
                email=email,
                key=uuid.uuid4(),
                tier="free",
                is_active=True,
            )

            logger.info("event=registration_api_key_created api_key_id=%s email=%s", str(api_key.id), email)

            try:
                from api.queue.manager import TaskManager
                from api.tasks import send_api_key_email

                task_key = f"email_api_key:{api_key.id}"
                verification_link = request.build_absolute_uri(f"/api/auth/verify/{api_key.id}/")
                TaskManager.enqueue(task_key, send_api_key_email, str(api_key.id), api_key.email, verification_link)
            except Exception:
                logger.exception("event=registration_enqueue_failed email=%s", email)

            return Response(
                {
                    "message": "API key created successfully. A verification email is being sent.",
                    "email": email,
                    "api_key": str(api_key.key),
                    "tier": api_key.tier,
                },
                status=201,
            )

        except Exception as exc:
            logger.exception("event=registration_create_failed email=%s error=%s", email, exc)
            return Response(
                {"error": "Registration failed. Please try again."},
                status=500,
            )




class APIKeyMeView(APIView):
    """
    GET /api/auth/me/
    Returns current key details and live rate limit state from Redis 4.
    Requires valid API key.
    """
    authentication_classes = [APIKeyAuthentication]
    throttle_classes = []  # me endpoint never throttled

    @extend_schema(
        responses={200: OpenApiResponse(description="Current key details and rate limit state")},
        summary="Get your API key details and quota",
        description=(
            "Returns your tier, rate limit bucket state, and daily usage. "
            "Check this before making expensive telemetry requests."
        ),
    )
    def get(self, request):
        api_key = request.auth
        if not api_key or not hasattr(api_key, "key"):
            return Response({"error": "Not authenticated"}, status=401)

        from api.throttling import TIER_CONFIGS, _get_redis
        config = TIER_CONFIGS.get(api_key.tier, TIER_CONFIGS["free"])

        # Read live token state from Redis 4
        tokens_remaining = config["capacity"]
        daily_used = 0
        try:
            redis = _get_redis()
            if redis:
                key_str = str(api_key.key)
                raw_tokens = redis.get(f"tb:{key_str}:tokens")
                raw_last = redis.get(f"tb:{key_str}:last")
                if raw_tokens and raw_last:
                    import time as _time
                    elapsed = max(0, _time.time() - float(raw_last))
                    tokens_remaining = min(
                        config["capacity"],
                        float(raw_tokens) + (elapsed * config["refill"])
                    )
                    tokens_remaining = round(tokens_remaining, 1)

                from datetime import date
                day_key = f"tb:{key_str}:day:{date.today().isoformat()}"
                daily_used = int(redis.get(day_key) or 0)
        except Exception as exc:
            logger.warning("event=me_redis_error error=%s", exc)

        daily_remaining = None
        if config["daily_cap"] is not None:
            daily_remaining = max(0, config["daily_cap"] - daily_used)

        return Response({
            "email": api_key.email,
            "tier": api_key.tier,
            "is_active": api_key.is_active,
            "created_at": api_key.created_at,
            "last_used_at": api_key.last_used_at,
            "total_requests": api_key.request_count,
            "rate_limits": {
                "bucket_capacity": config["capacity"],
                "refill_rate_per_second": config["refill"],
                "daily_cap": config["daily_cap"],
                "tokens_remaining_now": tokens_remaining,
                "daily_used_today": daily_used,
                "daily_remaining_today": daily_remaining,
            },
            "endpoint_costs": {
                "schedule_results_weather_incidents": 1,
                "laps_pace_stints_positions_pitstops_drs_trackstatus": 2,
                "full_session_unified": 3,
                "telemetry_single_lap": 5,
                "telemetry_overlay_two_drivers": 8,
            },
        })


class GenerateInternalKeyView(APIView):
    """
    POST /api/auth/{INTERNAL_KEY_PATH}/

    Generates or retrieves the internal API key for the frontend.

    Protected by:
      1. AdminEndpointThrottle — 3 attempts/hour per IP (brute-force guard)
      2. X-Admin-Password header — must match INTERNAL_KEY_PASSWORD from .env

    Store the returned key in .env as INTERNAL_API_KEY.
    Add to frontend as VITE_API_KEY or NEXT_PUBLIC_API_KEY.
    Never commit to source control.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = [AdminEndpointThrottle]
    renderer_classes = [JSONRenderer]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="X-Admin-Password",
                location=OpenApiParameter.HEADER,
                required=True,
                description="Admin password (INTERNAL_KEY_PASSWORD from .env)",
            )
        ],
        responses={
            200: OpenApiResponse(response=dict, description="Internal key retrieved."),
            201: OpenApiResponse(response=dict, description="Internal key created."),
            401: OpenApiResponse(response=dict, description="Invalid admin password"),
            500: OpenApiResponse(response=dict, description="INTERNAL_KEY_PASSWORD not configured in .env"),
        },
        auth=[{"XAdminSecret": []}],
    )
    def post(self, request):
        import hmac
        from django.conf import settings

        expected_password = getattr(settings, "INTERNAL_KEY_PASSWORD", "")
        provided_password = request.headers.get("X-Admin-Password", "")

        if not expected_password:
            return Response(
                {"error": "INTERNAL_KEY_PASSWORD not configured in .env"},
                status=500,
            )

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_password, expected_password):
            return Response(
                {"error": "Invalid admin password", "error_code": "UNAUTHORIZED"},
                status=401,
            )

        # Get or create internal key — idempotent
        api_key, created = APIKey.objects.get_or_create(
            email="internal@f1api.internal",
            defaults={
                "key": uuid.uuid4(),
                "tier": "internal",
                "is_active": True,
            },
        )

        # Ensure it stays internal and active if it already existed
        if api_key.tier != "internal" or not api_key.is_active:
            api_key.tier = "internal"
            api_key.is_active = True
            api_key.save(update_fields=["tier", "is_active"])

        logger.info(
            "event=internal_key_%s", "created" if created else "retrieved"
        )

        return Response(
            {
                "message": "Internal key created." if created else "Internal key retrieved.",
                "api_key": str(api_key.key),
                "tier": "internal",
                "rate_limits": {
                    "per_key_capacity": 500,
                    "per_key_refill_per_second": 5.0,
                    "per_ip_capacity": 200,
                    "per_ip_refill_per_second": 2.0,
                    "daily_cap": "unlimited",
                },
                "instructions": (
                    "Store this key in .env as INTERNAL_API_KEY. "
                    "Add to frontend as VITE_API_KEY or NEXT_PUBLIC_API_KEY. "
                    "Never commit to source control."
                ),
            },
            status=201 if created else 200,
        )
