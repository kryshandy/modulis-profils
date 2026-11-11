"""Settings used ONLY at image build time (`collectstatic` in docker/django/Dockerfile, prod stage).

prod.py refuses to start without real secrets (dedicated keys, Redis, secret ADMIN_URL, 2FA). They do
not exist at build time and must never be baked into an image, so the build uses this module: it
imports the common settings with throw-away values and only needs what collectstatic needs.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "build-only-not-a-secret")

from .base import *  # noqa: F403

DEBUG = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
