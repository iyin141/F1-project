"""
Backward-compatibility shim — imports redirected to api.constructors.services.

All new code should import from ``api.constructors.services`` directly.
"""
from api.constructors.services import get_constructor_standings  # noqa: F401
