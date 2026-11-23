from django.apps import AppConfig


class AssistantConfig(AppConfig):
    name = "api.assistant"
    label = "assistant"  # own label = own migrations folder, so feature branches never number-collide in api/migrations
    default_auto_field = "django.db.models.BigAutoField"
