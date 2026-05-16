"""
Backward-compatibility shim for driver standings service.
Redirects to the new api.drivers.services module.
"""
from api.drivers.services.standings import get_driver_standings  # noqa: F401
