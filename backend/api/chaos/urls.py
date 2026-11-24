from django.urls import path

from .views import (
    ChaosCircuitHistoryAPIView,
    ChaosCircuitListAPIView,
    ChaosCircuitsSummaryAPIView,
    ChaosDriverProfileAPIView,
    ChaosDriversAPIView,
    ChaosLapsAPIView,
    ChaosModelAPIView,
    ChaosRaceAPIView,
)

urlpatterns = [
    path("races/<int:year>/<int:round_number>/", ChaosRaceAPIView.as_view(), name="chaos-race"),
    path("races/<int:year>/<int:round_number>/drivers/", ChaosDriversAPIView.as_view(), name="chaos-race-drivers"),
    path("races/<int:year>/<int:round_number>/laps/", ChaosLapsAPIView.as_view(), name="chaos-race-laps"),
    path("circuits/", ChaosCircuitListAPIView.as_view(), name="chaos-circuit-list"),
    path("circuits/summary/", ChaosCircuitsSummaryAPIView.as_view(), name="chaos-circuits-summary"),
    path("circuits/<str:circuit>/history/", ChaosCircuitHistoryAPIView.as_view(), name="chaos-circuit-history"),
    path("drivers/<str:code>/profile/", ChaosDriverProfileAPIView.as_view(), name="chaos-driver-profile"),
    path("model/", ChaosModelAPIView.as_view(), name="chaos-model"),
]
