from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY, env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# A shared cache is mandatory: per-process locmem would multiply every rate limit by the
# number of Gunicorn workers and reset them on each restart.
CACHES = {"default": env.cache("CACHE_URL")}
if CACHES["default"]["BACKEND"].endswith(("LocMemCache", "DummyCache")):
    raise ImproperlyConfigured("CACHE_URL must point to Redis in production.")

# The SMS backend must be a real provider: Console/Memory would expose OTP codes in logs.
SMS_BACKEND = env("SMS_BACKEND")
if SMS_BACKEND.rsplit(".", 1)[-1] in {"ConsoleSmsBackend", "MemorySmsBackend"}:
    raise ImproperlyConfigured("SMS_BACKEND must be a real SMS provider in production.")

# Secrets must be distinct, explicit values (never derived from SECRET_KEY in production).
for _name in ("OTP_HMAC_KEY", "ANALYTICS_SALT", "CARD_ACTIVATION_KEY", "SLUG_HASH_KEY"):
    _value = env(_name, default="")
    if len(_value) < 32 or _value == SECRET_KEY:
        raise ImproperlyConfigured(f"{_name} must be set to a dedicated random value (≥ 32 chars).")
