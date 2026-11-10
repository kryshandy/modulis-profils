"""Common settings for every environment.

Environment-specific values come from environment variables (see `.env.example`).
"""

from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Absolute public base URL of the platform, without trailing slash. Used for canonical URLs,
# sitemaps, QR codes and printed card URLs (format frozen forever, see ADR-0003).
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")
SITE_NAME = env("SITE_NAME", default="Modulis Profils")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    # Third party
    "django_htmx",
    "csp",
    "huey.contrib.djhuey",
    # Local apps
    "apps.core",
    "apps.accounts",
    "apps.profiles",
    "apps.cards",
    "apps.seo",
    "apps.analytics",
    "apps.moderation",
    "apps.billing",
    "apps.dashboard",
    "apps.public",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Must sit ABOVE LocaleMiddleware: drops its `Vary: Accept-Language` on public pages (CDN cache).
    "apps.public.middleware.PublicHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AdminLoginThrottleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "csp.context_processors.nonce",
                "apps.core.context_processors.site",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "dashboard:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", _("Français")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

CACHES = {
    "default": env.cache("CACHE_URL", default="locmemcache://modulis"),
}

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days: pros stay logged in on their phone.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Content Security Policy (django-csp 4): no inline script, no eval.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://challenges.cloudflare.com"],
        "style-src": ["'self'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-src": ["https://challenges.cloudflare.com"],
        "frame-ancestors": ["'none'"],
        "form-action": ["'self'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
    },
}

# Background tasks (ADR-0002).
HUEY = {
    "huey_class": env("HUEY_CLASS", default="huey.SqliteHuey"),
    "name": "modulis",
    "immediate": env.bool("HUEY_IMMEDIATE", default=False),
    "utc": True,
    "consumer": {"workers": 2, "worker_type": "thread"},
}
if HUEY["huey_class"] == "huey.SqliteHuey":
    HUEY["filename"] = str(BASE_DIR / "huey.sqlite3")
else:
    HUEY["url"] = env("REDIS_URL", default="redis://redis:6379/1")

# --- Business settings -----------------------------------------------------------------------

# OTP by SMS only (ADR-0004).
OTP_LENGTH = 6
OTP_TTL_SECONDS = 5 * 60
OTP_MAX_ATTEMPTS = 5
OTP_MAX_SENDS_PER_PHONE_PER_HOUR = 3
OTP_MAX_SENDS_PER_IP_PER_HOUR = 10
OTP_MAX_SENDS_PER_DAY_GLOBAL = env.int("OTP_MAX_SENDS_PER_DAY_GLOBAL", default=2000)
OTP_ALLOWED_PREFIXES = env.list("OTP_ALLOWED_PREFIXES", default=["+237"])
OTP_HMAC_KEY = env("OTP_HMAC_KEY", default=SECRET_KEY)
SMS_BACKEND = env("SMS_BACKEND", default="apps.accounts.sms.ConsoleSmsBackend")
DEFAULT_PHONE_REGION = "CM"

# Cloudflare Turnstile (bot challenge before sending an OTP). Empty = disabled (dev/tests).
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", default="")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")

# Cards (ADR-0005).
CARD_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CARD_CODE_LENGTH = 7
CARD_ACTIVATION_CODE_LENGTH = 8
CARD_ACTIVATION_MAX_ATTEMPTS_PER_IP_HOUR = 5

# SEO (§6 of the plan).
SEO_INDEXABLE_MIN_SCORE = 70
SEO_MIN_BIO_CHARS = 120
SEO_MIN_OWN_WORDS = 60
SEO_DIRECTORY_MIN_PROFILES = 3
SLUG_MAX_CHANGES_PER_YEAR = 3

# Indexing notifications with kliz (docs/etudes/kliz.md). Disabled outside production.
KLIZ_ENABLED = env.bool("KLIZ_ENABLED", default=False)
KLIZ_INDEXNOW_KEY = env("KLIZ_INDEXNOW_KEY", default="")
KLIZ_GSC_SITE = env("KLIZ_GSC_SITE", default="")
KLIZ_GSC_SERVICE_ACCOUNT_FILE = env("KLIZ_GSC_SERVICE_ACCOUNT_FILE", default="")

# Analytics: salt for daily visitor hashes (never store raw IPs).
ANALYTICS_SALT = env("ANALYTICS_SALT", default=SECRET_KEY)
# Direct peers allowed to set CF-Connecting-IP / X-Real-IP (e.g. the local Nginx: 127.0.0.1).
# Empty = forwarded headers are ignored. See apps.core.utils.client_ip.
TRUSTED_PROXY_IPS = env.list("TRUSTED_PROXY_IPS", default=[])

# Dedicated keys (rotating SECRET_KEY must never invalidate printed cards or erased-slug hashes).
CARD_ACTIVATION_KEY = env("CARD_ACTIVATION_KEY", default=SECRET_KEY)
SLUG_HASH_KEY = env("SLUG_HASH_KEY", default=SECRET_KEY)

# Staff sessions are short (pros stay logged in 30 days on their phone, staff 8 hours).
STAFF_SESSION_AGE = 8 * 60 * 60
ADMIN_LOGIN_MAX_ATTEMPTS_PER_HOUR = 10

ADMIN_URL = env("ADMIN_URL", default="gestion/")

# Support contact shown in the pro space help page (E.164, WhatsApp). Empty = hidden.
SUPPORT_WHATSAPP = env("SUPPORT_WHATSAPP", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "kliz": {"level": "INFO"},
    },
}
