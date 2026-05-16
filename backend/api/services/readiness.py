"""
Backward-compatibility shim — imports redirected to api.common.readiness.

All new code should import from ``api.common.readiness`` directly.
"""
from api.common.readiness import (  # noqa: F401
    build_readiness,
    is_data_unavailable_error,
    classify_fastf1_exception,
)
