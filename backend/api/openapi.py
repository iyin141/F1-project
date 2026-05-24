"""
drf-spectacular OpenAPI extensions.
Registers APIKeyAuthentication so Swagger knows how to document it.
Import this in api/apps.py ready() to ensure registration on startup.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class APIKeyAuthenticationExtension(OpenApiAuthenticationExtension):
    target_class = 'api.auth.APIKeyAuthentication'
    name = 'ApiKeyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-API-Key',
            'description': (
                'API key UUID. Register at /api/auth/register/ to get yours. '
                'Example: 3eb017f4-ace9-4aee-8900-3124820e056c'
            ),
        }

    def get_security_requirement(self, auto_schema):
        return {self.name: []}
