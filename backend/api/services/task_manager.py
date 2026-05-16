"""
Backward-compatibility shim — imports redirected to api.queue.manager.

All new code should import from ``api.queue.manager`` directly.
"""
from api.queue.manager import TaskManager  # noqa: F401
