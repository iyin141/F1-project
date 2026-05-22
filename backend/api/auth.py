"""
API Key authentication for tier-based rate limiting.

Integrates with APIKey model for authentication and tier-based request tracking.
"""

from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from typing import Optional, Tuple
import uuid

from api.models import APIKey


class APIKeyAuthentication(TokenAuthentication):
    """
    Authenticate requests using API keys from the APIKey model.
    
    Scheme: Authorization: ApiKey <uuid>
    
    On successful authentication:
    - Sets request.auth to the APIKey instance
    - Sets request.user to AnonymousUser (API key auth doesn't authenticate users)
    - Marks key as used and increments request_count
    """
    
    keyword = 'ApiKey'
    
    def authenticate_credentials(self, key: str) -> Tuple[object, Optional[APIKey]]:
        """
        Authenticate the key and mark it as used.
        
        Args:
            key: The API key UUID string
            
        Returns:
            Tuple of (user, auth) where user is None (we use auth to identify tier)
            
        Raises:
            AuthenticationFailed: If key is invalid or inactive
        """
        try:
            # Parse the key as UUID
            key_uuid = uuid.UUID(key)
        except (ValueError, AttributeError):
            raise AuthenticationFailed('Invalid API key format.')
        
        try:
            # Fetch the API key record
            api_key = APIKey.objects.select_for_update().get(key=key_uuid)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key.')
        
        # Check if key is active
        if not api_key.is_active:
            raise AuthenticationFailed('API key is inactive.')
        
        # Mark key as used (increments request_count and updates last_used_at)
        api_key.mark_used()
        
        # Return (user, auth) tuple — user is None, auth is the APIKey instance
        return (None, api_key)
    
    def authenticate(self, request: Request) -> Optional[Tuple]:
        """
        Extract and authenticate the API key from the Authorization header.
        
        Args:
            request: The incoming request
            
        Returns:
            Tuple of (user, auth) if authenticated, None otherwise
        """
        # Get Authorization header
        auth = request.META.get('HTTP_AUTHORIZATION', '').split()
        
        # Check if Authorization header exists and has correct format
        if not auth or auth[0].lower() != self.keyword.lower():
            return None
        
        # Require exactly 2 parts: "ApiKey" and "<key>"
        if len(auth) != 2:
            raise AuthenticationFailed('Invalid Authorization header format.')
        
        # Authenticate using the key
        return self.authenticate_credentials(auth[1])
