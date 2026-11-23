from django.apps import AppConfig


class ChaosConfig(AppConfig):
    name = "api.chaos"
    label = "chaos"  # own label = own migrations folder, so feature branches never number-collide in api/migrations
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
