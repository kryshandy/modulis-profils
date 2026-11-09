from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# Show OTP codes in the console instead of sending SMS.
SMS_BACKEND = env("SMS_BACKEND", default="apps.accounts.sms.ConsoleSmsBackend")

# Static files without manifest in dev (no collectstatic needed).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
