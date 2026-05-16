"""
Backward-compatibility shim — imports redirected to api.session.runtime.

All new code should import from ``api.session.runtime`` directly.
"""
from api.session.runtime import fastf1  # noqa: F401
