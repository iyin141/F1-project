"""
Backward-compatibility shim for driver career service.
Redirects to the new api.drivers.services module.
"""
from api.drivers.services.career import get_driver_career
from api.drivers.services.season import get_driver_season

class DriverCareerService:
    def get_driver_career(self, driver_code, skip_cache=False):
        return get_driver_career(driver_code, skip_cache)

    def get_driver_season(self, driver_code, year):
        return get_driver_season(driver_code, year)
