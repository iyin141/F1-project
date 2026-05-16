"""URL configuration for the constructors domain."""
from django.urls import path
from api.constructors.views import ConstructorStandingsAPIView

urlpatterns = [
    path("<int:year>/", ConstructorStandingsAPIView.as_view(), name="constructor-standings"),
]
