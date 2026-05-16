"""URL configuration for the schedule domain."""
from django.urls import path
from api.schedule.views import SeasonScheduleAPIView, RaceDetailAPIView

urlpatterns = [
    path('<int:year>/', SeasonScheduleAPIView.as_view(), name='races-by-year'),
    path('<int:year>/<int:round_number>/', RaceDetailAPIView.as_view(), name='race-detail'),
]
