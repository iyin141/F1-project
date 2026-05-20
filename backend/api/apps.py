from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
    
    def ready(self):
        """Register Django signals."""
        import api.signals  # noqa: F401
