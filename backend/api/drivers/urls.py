"""URL configuration for the drivers domain."""
from django.urls import path
from api.drivers.views import (
    DriverStandingsAPIView,
    DriverCareerAPIView,
    DriverSeasonAPIView,
)

urlpatterns = [
    # Driver Standings
    # Support both /api/drivers/standings/<year>/ and legacy /api/drivers/<year>/ used by tests
    path("standings/<int:year>/", DriverStandingsAPIView.as_view(), name="driver-standings"),
    path("<int:year>/", DriverStandingsAPIView.as_view(), name="driver-standings-year"),

    # Driver Career
    path("<str:driver_code>/career/", DriverCareerAPIView.as_view(), name="driver-career"),

    # Driver Season Breakdown
    path("<str:driver_code>/<int:year>/", DriverSeasonAPIView.as_view(), name="driver-season"),
]
