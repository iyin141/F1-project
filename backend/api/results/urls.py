"""URL configuration for the results domain."""
from django.urls import path
from api.results.views import (
    RaceResultsAPIView,
    QualifyingResultsAPIView,
    SprintResultsAPIView,
    SprintShootoutResultsAPIView,
    PracticeSessionAPIView,
    WeekendResultsAPIView
)

urlpatterns = [
    path('<int:year>/<int:round_number>/results/', RaceResultsAPIView.as_view(), name='race-results'),
    path('<int:year>/<int:round_number>/weekend/', WeekendResultsAPIView.as_view(), name='weekend-results'),
    path('<int:year>/<int:round_number>/qualifying/', QualifyingResultsAPIView.as_view(), name='qualifying-results'),
    path('<int:year>/<int:round_number>/sprint/', SprintResultsAPIView.as_view(), name='sprint-results'),
    path('<int:year>/<int:round_number>/sprint-shootout/', SprintShootoutResultsAPIView.as_view(), name='sprint-shootout-results'),
    path('<int:year>/<int:round_number>/practice/<str:session_name>/', PracticeSessionAPIView.as_view(), name='practice-session-results'),
]
