from django.urls import path

from .views import MiniSectorsAPIView, TelemetryDeltaAPIView, TrackMapAPIView

urlpatterns = [
    path("track-map/", TrackMapAPIView.as_view(), name="analysis-track-map"),
    path("mini-sectors/", MiniSectorsAPIView.as_view(), name="analysis-mini-sectors"),
    path("telemetry/delta/", TelemetryDeltaAPIView.as_view(), name="analysis-telemetry-delta"),
]
