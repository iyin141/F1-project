"""
URL configuration for f1_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from django.http import JsonResponse

def api_root(request):
    return JsonResponse({
        "message": "Welcome to F1 Control Room API",
        "endpoints": {
            "docs": "/api/docs/",
            "redoc": "/api/redoc/",
            "schema": "/api/schema/",
            "api_base": "/api/",
            "resources": {
                "races": "/api/races/",
                "race_results": "/api/races/<year>/<round>/results/",
                "race_schedule": "/api/races/<year>/",
                "drivers": "/api/drivers/",
                "driver_career": "/api/drivers/<driver_code>/career/",
                "driver_season": "/api/drivers/<driver_code>/<year>/",
                "driver_standings": "/api/drivers/standings/<year>/",
                "unified_session": "/api/unified/races/<year>/<round>/full-session/?include=...",
                "unified_weather": "/api/unified/races/<year>/<round>/weather/",
                "unified_pit_stops": "/api/unified/races/<year>/<round>/pit-stops/",
                "unified_incidents": "/api/unified/races/<year>/<round>/incidents/",
                "unified_positions": "/api/unified/races/<year>/<round>/positions/",
                "unified_drs": "/api/unified/races/<year>/<round>/drs/",
                "unified_track_status": "/api/unified/races/<year>/<round>/track-status/",
                "telemetry_summary": "/api/analysis/races/<year>/<round>/telemetry-summary/",
                "telemetry": "/api/analysis/races/<year>/<round>/telemetry/",
                "telemetry_overlay": "/api/analysis/races/<year>/<round>/telemetry/overlay/",
                "laps": "/api/analysis/races/<year>/<round>/laps/",
                "sectors": "/api/analysis/races/<year>/<round>/sector-analysis/",
                "stints": "/api/analysis/races/<year>/<round>/stint-analysis/",
                "pace": "/api/analysis/races/<year>/<round>/pace-analysis/",
                "tyre_strategy": "/api/analysis/races/<year>/<round>/tyre-strategy/",
            }
        }
    })

urlpatterns = [
    path('', api_root, name='root'),
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/', include('api.urls')),
]
