"""
Backward-compatibility shim for driver views.
Redirects to the new api.drivers.views module.
"""
from api.drivers.views import DriverCareerAPIView, DriverSeasonAPIView  # noqa: F401
