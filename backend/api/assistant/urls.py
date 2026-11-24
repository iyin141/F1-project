from django.urls import path

from .views import AskAPIView, AskEventsAPIView

urlpatterns = [
    path("ask", AskAPIView.as_view(), name="assistant-ask"),
    path("ask/", AskAPIView.as_view()),
    path("ask/<str:task_key>/events", AskEventsAPIView.as_view(), name="assistant-ask-events"),
]
