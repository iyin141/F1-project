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
