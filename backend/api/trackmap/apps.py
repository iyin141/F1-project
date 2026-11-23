from django.apps import AppConfig


class TrackmapConfig(AppConfig):
    name = "api.trackmap"
    label = "trackmap"  # own label = own migrations folder, so feature branches never number-collide in api/migrations
    default_auto_field = "django.db.models.BigAutoField"
