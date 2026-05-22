"""
API key registration and lifecycle management endpoints.

Provides endpoints for:
- New API key registration (email verification required)
- Tier selection and upgrades
- API key renewal and revocation
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT
from rest_framework.permissions import AllowAny
import logging
import uuid

from api.models import APIKey
from api.tasks import send_verification_email
from django.db import IntegrityError

logger = logging.getLogger(__name__)


class RegisterAPIView(APIView):
    """
    Register for a new API key.
    
    POST /api/auth/register/
    {
        "email": "user@example.com",
        "tier": "free"  # or basic, pro, enterprise
    }
    
    Response (201):
    {
        "id": "<uuid>",
        "email": "user@example.com",
        "key": "<uuid>",
        "tier": "free",
        "status": "pending_verification"
    }
    """
    
    permission_classes = [AllowAny]
    VALID_TIERS = ['free', 'basic', 'pro', 'enterprise']
    
    def post(self, request):
        """
        Register a new API key with email verification.
        
        Validates email format, checks for duplicates, creates inactive key,
        and sends verification email.
        """
        email = request.data.get('email', '').strip().lower()
        tier = request.data.get('tier', 'free').lower()
        
        # Validate email
        if not email or '@' not in email:
            return Response(
                {'error': 'Invalid email address'},
                status=HTTP_400_BAD_REQUEST
            )
        
        # Validate tier
        if tier not in self.VALID_TIERS:
            return Response(
                {'error': f'Invalid tier. Valid options: {", ".join(self.VALID_TIERS)}'},
                status=HTTP_400_BAD_REQUEST
            )
        
        # Check if email already registered
        if APIKey.objects.filter(email=email).exists():
            return Response(
                {'error': 'Email already registered'},
                status=HTTP_409_CONFLICT
            )
        
        try:
            # Create new API key (inactive until verified)
            api_key = APIKey.objects.create(
                email=email,
                tier=tier,
                is_active=False,  # Inactive until email verified
            )
            
            # Send verification email
            send_verification_email.delay(
                task_key=f'email_verification:{api_key.id}',
                api_key_id=str(api_key.id),
                email=email,
                verification_link=f'https://api.example.com/auth/verify/{api_key.id}/'
            )
            
            logger.info(
                'event=registration_created email=%s tier=%s api_key_id=%s',
                email, tier, api_key.id
            )
            
            return Response(
                {
                    'id': str(api_key.id),
                    'email': api_key.email,
                    'key': str(api_key.key),
                    'tier': api_key.tier,
                    'status': 'pending_verification',
                },
                status=HTTP_201_CREATED
            )
        
        except IntegrityError:
            # Race condition: email registered between check and create
            return Response(
                {'error': 'Email already registered'},
                status=HTTP_409_CONFLICT
            )
        except Exception as e:
            logger.error(
                'event=registration_error email=%s error=%s',
                email, str(e)
            )
            return Response(
                {'error': 'Registration failed. Please try again.'},
                status=HTTP_400_BAD_REQUEST
            )


class VerifyEmailAPIView(APIView):
    """
    Verify API key email and activate the key.
    
    GET /api/auth/verify/<api_key_id>/
    
    Response (200):
    {
        "id": "<uuid>",
        "email": "user@example.com",
        "key": "<uuid>",
        "tier": "free",
        "status": "active",
        "message": "Email verified. Your API key is now active."
    }
    """
    
    permission_classes = [AllowAny]
    
    def get(self, request, api_key_id):
        """
        Verify email and activate API key.
        """
        try:
            api_key_uuid = uuid.UUID(api_key_id)
        except (ValueError, AttributeError):
            return Response(
                {'error': 'Invalid API key ID'},
                status=HTTP_400_BAD_REQUEST
            )
        
        try:
            api_key = APIKey.objects.get(id=api_key_uuid)
        except APIKey.DoesNotExist:
            return Response(
                {'error': 'API key not found'},
                status=HTTP_400_BAD_REQUEST
            )
        
        if api_key.is_active:
            return Response(
                {
                    'id': str(api_key.id),
                    'email': api_key.email,
                    'tier': api_key.tier,
                    'status': 'already_verified',
                    'message': 'This API key was already verified.',
                }
            )
        
        # Activate the key
        api_key.is_active = True
        api_key.save()
        
        # Send welcome email
        send_welcome_email.delay(
            task_key=f'email_welcome:{api_key.id}',
            api_key_id=str(api_key.id),
            email=api_key.email,
            tier=api_key.tier,
        )
        
        logger.info(
            'event=email_verified email=%s api_key_id=%s',
            api_key.email, api_key.id
        )
        
        return Response(
            {
                'id': str(api_key.id),
                'email': api_key.email,
                'key': str(api_key.key),
                'tier': api_key.tier,
                'status': 'active',
                'message': 'Email verified. Your API key is now active.',
            }
        )


class RevokeAPIKeyView(APIView):
    """
    Revoke an API key (deactivate).
    
    POST /api/auth/revoke/
    Authorization: ApiKey <key>
    
    Response (200):
    {
        "id": "<uuid>",
        "status": "revoked",
        "message": "API key revoked successfully."
    }
    """
    
    def post(self, request):
        """
        Revoke the authenticated API key.
        """
        from api.models import APIKey
        
        if not hasattr(request, 'auth') or not isinstance(request.auth, APIKey):
            return Response(
                {'error': 'Authentication required'},
                status=HTTP_400_BAD_REQUEST
            )
        
        api_key = request.auth
        
        if not api_key.is_active:
            return Response(
                {'error': 'API key is already revoked'},
                status=HTTP_400_BAD_REQUEST
            )
        
        # Deactivate the key
        api_key.is_active = False
        api_key.save()
        
        # Send revocation email
        send_key_revocation_email.delay(
            task_key=f'email_revocation:{api_key.id}',
            api_key_id=str(api_key.id),
            email=api_key.email,
        )
        
        logger.info(
            'event=api_key_revoked email=%s api_key_id=%s',
            api_key.email, api_key.id
        )
        
        return Response(
            {
                'id': str(api_key.id),
                'status': 'revoked',
                'message': 'API key revoked successfully.',
            }
        )
