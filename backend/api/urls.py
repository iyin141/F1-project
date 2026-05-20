from django.urls import path, include
from . import views
from .views.task_status import TaskStatusAPIView

app_name = 'api'

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
    # Task Status — Phase 5: Non-blocking views with async task polling
    # ========================================================================
    path('tasks/<str:task_id>/status/', TaskStatusAPIView.as_view(), name='task-status'),
    
    # ========================================================================
]
