"""URL configuration for the drivers domain."""
from django.urls import path
from api.drivers.views import (
    DriverStandingsAPIView,
    DriverCareerAPIView,
    DriverSeasonAPIView,
    SearchDriversAPIView,
    SearchDriverByNameAPIView,
    SyncSingleYearAPIView,
    SyncAllYearsAPIView,
    SyncChampionsAPIView,
)

urlpatterns = [
    # Year-level driver championship standings
    path("<int:year>/", DriverStandingsAPIView.as_view(), name="driver-standings"),

    # Driver Career
    path("<str:driver_code>/career/", DriverCareerAPIView.as_view(), name="driver-career"),

    # Driver Season Breakdown
    path("<str:driver_code>/<int:year>/", DriverSeasonAPIView.as_view(), name="driver-season"),

    # Phase 8: Driver Search & Sync
    path("search/", SearchDriversAPIView.as_view(), name="driver-search"),
    path("search-by-name/", SearchDriverByNameAPIView.as_view(), name="driver-search-by-name"),
    path("sync/all/", SyncAllYearsAPIView.as_view(), name="driver-sync-all"),
    path("sync/<int:year>/", SyncSingleYearAPIView.as_view(), name="driver-sync-year"),

    # Champion Sync
    path("champions/sync/", SyncChampionsAPIView.as_view(), name="champions-sync"),
    path("champions/sync/<int:year>/", SyncChampionsAPIView.as_view(), name="champions-sync-year"),
]
