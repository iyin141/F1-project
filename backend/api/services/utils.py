"""
Backward-compatibility shim — imports redirected to api.common.utils.

All new code should import from ``api.common.utils`` directly.
"""
from api.common.utils import (  # noqa: F401
    is_current_year,
    is_round_completed,
)
