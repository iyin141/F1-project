from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
    
    def ready(self):
        """Register Django signals and OpenAPI extensions."""
        import api.signals  # noqa: F401
        import api.openapi  # noqa: F401 — registers OpenAPI auth extension
        # Check Redis instances at startup and warn if unreachable
        try:
            self._check_redis_instances()
        except Exception:
            # Don't prevent app startup if the check itself errors
            pass

    def _check_redis_instances(self):
        import logging
        logger = logging.getLogger(__name__)

        REDIS_INSTANCES = {
            "app_cache":     ("default",          6379),
            "telemetry":     ("telemetry_cache",  6380),
            "celery_broker": ("N/A",              6381),
            "rate_limiting": ("rate_limit",       6382),
        }

        from django.core.cache import caches
        for name, (cache_name, port) in REDIS_INSTANCES.items():
            if cache_name == "N/A":
                continue
            try:
                # Attempt to ping the Redis client
                client = caches[cache_name].client.get_client()
                client.ping()
                logger.info("event=redis_ok instance=%s port=%s", name, port)
            except Exception as e:
                logger.warning(
                    "event=redis_unavailable instance=%s port=%s error=%s",
                    name, port, e
                )
