from django.urls import path, include
from django.conf import settings as django_settings

from api.schedule.views import SeasonScheduleAPIView, RaceDetailAPIView
from api.constructors.views import ConstructorStandingsAPIView
from api.session.views import (
    AnalysisLapsAPIView, AnalysisStintsAPIView, AnalysisPaceAPIView,
    AnalysisTyreStrategyAPIView, AnalysisSectorAPIView, AnalysisTelemetryAPIView,
    AnalysisTelemetryOverlayAPIView, AnalysisTelemetrySummaryAPIView,
    UnifiedFullSessionAPIView, UnifiedWeatherAPIView, UnifiedPitStopsAPIView,
    UnifiedIncidentsAPIView, UnifiedPositionsAPIView, UnifiedDRSAPIView,
    UnifiedTrackStatusAPIView
)

from api.core.registration import (
    RegisterAPIView,
    APIKeyMeView,
    GenerateInternalKeyView,
)
from api.core.task_management import (
    TaskDetailsView, TaskCancelView, TaskRetryView,
    TaskQueueStatsView, TaskCleanupView
)

app_name = 'api'

_internal_key_path = getattr(django_settings, "INTERNAL_KEY_PATH", "internal-key")
urlpatterns = [
    path('races/', include('api.schedule.urls')),
    path('races/', include('api.results.urls')),
    
    # Session Analysis
    path('analysis/races/<int:year>/<int:round_number>/laps/', AnalysisLapsAPIView.as_view(), name='analysis-laps'),
    path('analysis/races/<int:year>/<int:round_number>/stints/', AnalysisStintsAPIView.as_view(), name='analysis-stints'),
    path('analysis/races/<int:year>/<int:round_number>/pace/', AnalysisPaceAPIView.as_view(), name='analysis-pace'),
    path('analysis/races/<int:year>/<int:round_number>/tyre-strategy/', AnalysisTyreStrategyAPIView.as_view(), name='analysis-tyre-strategy'),
    path('analysis/races/<int:year>/<int:round_number>/sector-analysis/', AnalysisSectorAPIView.as_view(), name='analysis-sector-analysis'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/', AnalysisTelemetryAPIView.as_view(), name='analysis-telemetry'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/overlay/', AnalysisTelemetryOverlayAPIView.as_view(), name='analysis-telemetry-overlay'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/summary/', AnalysisTelemetrySummaryAPIView.as_view(), name='analysis-telemetry-summary'),
    
    path('drivers/', include('api.drivers.urls')),
    path('constructors/<int:year>/', ConstructorStandingsAPIView.as_view(), name='constructor-standings'),
    
    # Unified Service Routes
    path('unified/races/<int:year>/<int:round_number>/full-session/', UnifiedFullSessionAPIView.as_view(), name='unified-full-session'),
    path('unified/races/<int:year>/<int:round_number>/weather/', UnifiedWeatherAPIView.as_view(), name='unified-weather'),
    path('unified/races/<int:year>/<int:round_number>/pit-stops/', UnifiedPitStopsAPIView.as_view(), name='unified-pit-stops'),
    path('unified/races/<int:year>/<int:round_number>/incidents/', UnifiedIncidentsAPIView.as_view(), name='unified-incidents'),
    path('unified/races/<int:year>/<int:round_number>/positions/', UnifiedPositionsAPIView.as_view(), name='unified-positions'),
    path('unified/races/<int:year>/<int:round_number>/drs/', UnifiedDRSAPIView.as_view(), name='unified-drs'),
    path('unified/races/<int:year>/<int:round_number>/track-status/', UnifiedTrackStatusAPIView.as_view(), name='unified-track-status'),
    
    # Auth & Tasks
    path('auth/register/', RegisterAPIView.as_view(), name='register'),
    path('auth/me/', APIKeyMeView.as_view(), name='api-key-me'),
    path(f'auth/{_internal_key_path}/', GenerateInternalKeyView.as_view(), name='generate-internal-key'),
]
