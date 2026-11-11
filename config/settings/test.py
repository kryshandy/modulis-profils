from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
SITE_URL = "https://profils.test"
# SQLite in memory by default (fast, venv). Docker `make dtest` sets TEST_DATABASE_URL to PostgreSQL.
DATABASES = {"default": env.db("TEST_DATABASE_URL", default="sqlite:///:memory:")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast tests only
SMS_BACKEND = "apps.accounts.sms.MemorySmsBackend"
HUEY = {"huey_class": "huey.MemoryHuey", "name": "test", "immediate": True}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
TURNSTILE_SITE_KEY = ""
TURNSTILE_SECRET_KEY = ""
KLIZ_ENABLED = False
TRUSTED_PROXY_IPS: list[str] = []
STAFF_2FA_REQUIRED = True  # conftest marks force_login() staff sessions as verified (apps.security.testing)
