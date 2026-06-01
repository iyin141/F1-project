from django.urls import path, include
from django.conf import settings as django_settings
from . import views
from .views.task_status import TaskStatusAPIView
from .views.registration import (
    RegisterAPIView,
    APIKeyMeView,
    GenerateInternalKeyView,
)
from .views.task_management import (
    TaskDetailsView, TaskCancelView, TaskRetryView,
    TaskQueueStatsView, TaskCleanupView
)

app_name = 'api'

_internal_key_path = getattr(django_settings, "INTERNAL_KEY_PATH", "internal-key")
urlpatterns = [
    path('races/', include('api.schedule.urls')),
    path('races/', include('api.results.urls')),
    path('analysis/races/<int:year>/<int:round_number>/laps/', views.AnalysisLapsAPIView.as_view(), name='analysis-laps'),
    path('analysis/races/<int:year>/<int:round_number>/stints/', views.AnalysisStintsAPIView.as_view(), name='analysis-stints'),
    path('analysis/races/<int:year>/<int:round_number>/pace/', views.AnalysisPaceAPIView.as_view(), name='analysis-pace'),
    path('analysis/races/<int:year>/<int:round_number>/tyre-strategy/', views.AnalysisTyreStrategyAPIView.as_view(), name='analysis-tyre-strategy'),
    path('analysis/races/<int:year>/<int:round_number>/sector-analysis/', views.AnalysisSectorAPIView.as_view(), name='analysis-sector-analysis'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/', views.AnalysisTelemetryAPIView.as_view(), name='analysis-telemetry'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/overlay/', views.AnalysisTelemetryOverlayAPIView.as_view(), name='analysis-telemetry-overlay'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/summary/', views.AnalysisTelemetrySummaryAPIView.as_view(), name='analysis-telemetry-summary'),
    path('drivers/', include('api.drivers.urls')),
    path('constructors/<int:year>/', views.ConstructorStandingsAPIView.as_view(), name='constructor-standings'),
    
    # ========================================================================
    # Unified Service Routes - Comprehensive FastF1 data via modular extractors
    # ========================================================================
    path('unified/races/<int:year>/<int:round_number>/full-session/', views.UnifiedFullSessionAPIView.as_view(), name='unified-full-session'),
    path('unified/races/<int:year>/<int:round_number>/weather/', views.UnifiedWeatherAPIView.as_view(), name='unified-weather'),
    path('unified/races/<int:year>/<int:round_number>/pit-stops/', views.UnifiedPitStopsAPIView.as_view(), name='unified-pit-stops'),
    path('unified/races/<int:year>/<int:round_number>/incidents/', views.UnifiedIncidentsAPIView.as_view(), name='unified-incidents'),
    path('unified/races/<int:year>/<int:round_number>/positions/', views.UnifiedPositionsAPIView.as_view(), name='unified-positions'),
    path('unified/races/<int:year>/<int:round_number>/drs/', views.UnifiedDRSAPIView.as_view(), name='unified-drs'),
    path('unified/races/<int:year>/<int:round_number>/track-status/', views.UnifiedTrackStatusAPIView.as_view(), name='unified-track-status'),
    
    # ========================================================================
  
    
    # ========================================================================
    # Authentication & Registration — API key lifecycle management (Module E)
    # ========================================================================
    path('auth/register/', RegisterAPIView.as_view(), name='register'),
    path('auth/me/', APIKeyMeView.as_view(), name='api-key-me'),
    path(f'auth/{_internal_key_path}/', GenerateInternalKeyView.as_view(), name='generate-internal-key'),
    
    # ========================================================================
]
