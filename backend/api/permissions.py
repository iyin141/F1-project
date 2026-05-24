from rest_framework.permissions import BasePermission


class IsAPIKeyAuthenticated(BasePermission):
    """
    Allow access only to requests with a valid API key.
    Checks request.auth (set by APIKeyAuthentication) not request.user.
    Exempt paths (docs, register, verify) return None from authenticate()
    which means request.auth is None — those views must set
    permission_classes = [] explicitly.
    """
    message = "API key required. Register at /api/auth/register/ to get one."

    def has_permission(self, request, view):
        return bool(
            request.auth is not None
            and hasattr(request.auth, "key")
            and request.auth.is_active
        )
