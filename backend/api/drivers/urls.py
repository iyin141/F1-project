"""URL configuration for the drivers domain."""
from django.urls import path
from api.drivers.views import (
    DriverStandingsAPIView,
    DriverCareerAPIView,
    DriverSeasonAPIView,
)

urlpatterns = [
    # Driver Standings
    path("standings/<int:year>/", DriverStandingsAPIView.as_view(), name="driver-standings"),

    # Driver Career
    path("<str:driver_code>/career/", DriverCareerAPIView.as_view(), name="driver-career"),

    # Driver Season Breakdown
    path("<str:driver_code>/<int:year>/", DriverSeasonAPIView.as_view(), name="driver-season"),
]
