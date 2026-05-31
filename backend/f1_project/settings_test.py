"""Test settings for local, deterministic unit test execution."""

from .settings import *  # noqa: F401,F403

# Use local SQLite for tests so test bootstrap is not blocked by remote DB DNS/network.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",
    }
}

# Keep test runs fast.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Ensure host checks do not fail under Django test client.
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# Use model sync for api app during tests to avoid PostgreSQL-specific migration SQL on SQLite.
MIGRATION_MODULES = {
    "api": None,
}

# Use in-memory caches for tests to avoid external Redis dependency
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
    "telemetry_cache": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
    "rate_limit": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

# Run Celery tasks eagerly in-process during tests to avoid broker dependency
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
 
# Use the fake FastF1 implementation in tests to prevent network calls
import os
os.environ.setdefault("USE_FAKE_FASTF1", "1")
os.environ.setdefault("USE_FAKE_JOLPICA", "0")
# Ensure tests import fixtures from the tests package when available
os.environ.setdefault("PYTHONPATH", os.pathsep.join([os.path.dirname(__file__), os.environ.get("PYTHONPATH", "")]))

# Inject a minimal fake `fastf1` module into `sys.modules` when tests opt-in
# to avoid importing the heavy upstream `fastf1` package (pyarrow/pandas
# C extensions) during Django app startup.
if os.environ.get("USE_FAKE_FASTF1", "0") == "1":
    import sys
    import types

    if "fastf1" not in sys.modules:
        fake_fastf1 = types.ModuleType("fastf1")

        def _fake_get_event_schedule(year):
            # lightweight empty DataFrame — safe for callers that check `.empty`
            import pandas as pd

            return pd.DataFrame()

        def _fake_get_session(year, round_number, session):
            # Minimal stand-in with `.results` and `.laps` attributes and a
            # no-op `load()` method so unit tests that patch deeper functions
            # can still call `fastf1.get_session` safely.
            class _DummySession:
                def __init__(self):
                    import pandas as pd

                    self.results = pd.DataFrame()
                    self.laps = pd.DataFrame()

                def load(self, **kwargs):
                    return None

            return _DummySession()

        fake_fastf1.get_event_schedule = _fake_get_event_schedule
        fake_fastf1.get_session = _fake_get_session
        sys.modules["fastf1"] = fake_fastf1

# During tests, disable file-based logging handlers to avoid file locks on CI/dev machines.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[%(asctime)s] %(levelname)s %(name)s | %(message)s", "datefmt": "%Y-%m-%d %H:%M:%S"}
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Test safety overrides -------------------------------------------------
# Prevent tests from making external Resend API calls by clearing the key and
# forcing a locmem email backend.
RESEND_API_KEY = ""
ANYMAIL = {}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Ensure a test internal API key is available so test clients automatically
# send `X-API-Key` headers via `api.tests.__init__`. Prefer using the
# environment or `.env` value if present, otherwise fall back to a safe static value.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY") or "11111111-1111-1111-1111-111111111111"

MIDDLEWARE = [
    # Test helper removed: per-test injection now handled by tests bootstrap
    # Request ID middleware and others; the middleware is only enabled in
    # `settings_test.py` so it cannot accidentally run in other environments.
    'api.common.request_id.RequestIdMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'api.middleware.csrf_exempt.CsrfExemptSessionMiddleware',  # Must run before CsrfViewMiddleware
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
# Do not disable API auth in tests; the test client will send the internal key.
# (Removed the AllowAny test override and TESTS_SKIP_API_AUTH flag.)

# NOTE: Per-test header injection is provided via `api.tests.mixins.TestDefaultAPIKeyMixin`.

