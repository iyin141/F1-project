from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('races/<int:year>/', views.SeasonScheduleAPIView.as_view(), name='races-by-year'),
    path('races/<int:year>/<int:round_number>/', views.RaceDetailAPIView.as_view(), name='race-detail'),
    path('races/<int:year>/<int:round_number>/results/', views.RaceResultsAPIView.as_view(), name='race-results'),
    path('races/<int:year>/<int:round_number>/qualifying/', views.QualifyingResultsAPIView.as_view(), name='qualifying-results'),
    path('races/<int:year>/<int:round_number>/practice/<str:session_name>/', views.PracticeSessionAPIView.as_view(), name='practice-session-results'),
    path('drivers/<int:year>/', views.DriverStandingsAPIView.as_view(), name='driver-standings'),
    path('constructors/<int:year>/', views.ConstructorStandingsAPIView.as_view(), name='constructor-standings'),
]
