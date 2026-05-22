"""
Backward-compatibility shim for driver views.
Redirects to the new api.drivers.views module and provides a small
compatibility service class used by older code and unit tests.
"""
from api.drivers.views import DriverCareerAPIView, DriverSeasonAPIView  # noqa: F401

# Compatibility service class: wraps the newer function-based services
# so legacy call sites (and tests) that patch `api.driver_views.DriverCareerService`
# continue to work.
from api.drivers.services.career import get_driver_career as _get_driver_career
from api.drivers.services.season import get_driver_season as _get_driver_season


class DriverCareerService:
	def get_driver_career(self, driver_code):
		return _get_driver_career(driver_code)

	def get_driver_season(self, driver_code, year):
		return _get_driver_season(driver_code, year)


# Also expose the compatibility class into the drivers.views module namespace
# so code importing the service from there will find it.
import api.drivers.views as _drv_mod
_drv_mod.DriverCareerService = DriverCareerService
