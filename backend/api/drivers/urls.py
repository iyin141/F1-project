"""URL configuration for the drivers domain."""
from django.urls import path
from api.drivers.views import (
    DriverStandingsAPIView,
    DriverCareerAPIView,
    DriverSeasonAPIView,
    SearchDriversAPIView,
    SearchDriverByNameAPIView,
)

urlpatterns = [
    # TODO: MOVE -> backend/api/sync_functions  # sync endpoints call DriverSyncService which will be refactored
    # Year-level driver championship standings
    path("<int:year>/", DriverStandingsAPIView.as_view(), name="driver-standings"),

    # Driver Career
    path("<str:driver_code>/career/", DriverCareerAPIView.as_view(), name="driver-career"),

    # Driver Season Breakdown
    path("<str:driver_code>/<int:year>/", DriverSeasonAPIView.as_view(), name="driver-season"),

    # Phase 8: Driver Search & Sync
    path("search/", SearchDriversAPIView.as_view(), name="driver-search"),
    path("search-by-name/", SearchDriverByNameAPIView.as_view(), name="driver-search-by-name"),
    # Sync endpoints removed: moved to CLI under backend/api/sync_functions/
]
