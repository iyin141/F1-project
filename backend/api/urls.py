from django.urls import path
from . import views
from .driver_views import DriverCareerAPIView, DriverSeasonAPIView

app_name = 'api'

urlpatterns = [
    path('races/<int:year>/', views.SeasonScheduleAPIView.as_view(), name='races-by-year'),
    path('races/<int:year>/<int:round_number>/', views.RaceDetailAPIView.as_view(), name='race-detail'),
    path('races/<int:year>/<int:round_number>/results/', views.RaceResultsAPIView.as_view(), name='race-results'),
    path('races/<int:year>/<int:round_number>/qualifying/', views.QualifyingResultsAPIView.as_view(), name='qualifying-results'),
    path('races/<int:year>/<int:round_number>/sprint/', views.SprintResultsAPIView.as_view(), name='sprint-results'),
    path('races/<int:year>/<int:round_number>/sprint-shootout/', views.SprintShootoutResultsAPIView.as_view(), name='sprint-shootout-results'),
    path('races/<int:year>/<int:round_number>/practice/<str:session_name>/', views.PracticeSessionAPIView.as_view(), name='practice-session-results'),
    path('analysis/races/<int:year>/<int:round_number>/laps/', views.AnalysisLapsAPIView.as_view(), name='analysis-laps'),
    path('analysis/races/<int:year>/<int:round_number>/stints/', views.AnalysisStintsAPIView.as_view(), name='analysis-stints'),
    path('analysis/races/<int:year>/<int:round_number>/pace/', views.AnalysisPaceAPIView.as_view(), name='analysis-pace'),
    path('analysis/races/<int:year>/<int:round_number>/tyre-strategy/', views.AnalysisTyreStrategyAPIView.as_view(), name='analysis-tyre-strategy'),
    path('analysis/races/<int:year>/<int:round_number>/sector-analysis/', views.AnalysisSectorAPIView.as_view(), name='analysis-sector-analysis'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/', views.AnalysisTelemetryAPIView.as_view(), name='analysis-telemetry'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/overlay/', views.AnalysisTelemetryOverlayAPIView.as_view(), name='analysis-telemetry-overlay'),
    path('analysis/races/<int:year>/<int:round_number>/telemetry/summary/', views.AnalysisTelemetrySummaryAPIView.as_view(), name='analysis-telemetry-summary'),
    path('drivers/<int:year>/', views.DriverStandingsAPIView.as_view(), name='driver-standings'),
    path('constructors/<int:year>/', views.ConstructorStandingsAPIView.as_view(), name='constructor-standings'),
    path('coverage/persistence/<int:year>/', views.PersistenceCoverageAPIView.as_view(), name='persistence-coverage'),
    path('coverage/persistence/<int:year>/<int:round_number>/', views.PersistenceCoverageAPIView.as_view(), name='persistence-coverage-round'),
    
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
    # Driver Routes - Career history and season breakdowns
    # MUST come AFTER /drivers/{year}/ to avoid URL conflicts
    # ========================================================================
    path('drivers/<str:driver_code>/career/', DriverCareerAPIView.as_view(), name='driver-career'),
    path('drivers/<str:driver_code>/<int:year>/', DriverSeasonAPIView.as_view(), name='driver-season'),
]
