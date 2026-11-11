# syntax=docker/dockerfile:1
# Image Django multi-étapes : "dev" (outils de test) et "prod" (Gunicorn), utilisateur non root.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo libwebp7 zlib1g curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base AS dev
# Same UID as the WSL user, so files written in the bind mount (migrations…) stay editable.
ARG UID=1000
RUN groupadd --gid ${UID} app && useradd --uid ${UID} --gid app --home /app app
COPY requirements/ /tmp/requirements/
RUN pip install -r /tmp/requirements/dev.txt
COPY docker/django/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/media && chown app:app /app/media
# No `USER app` here: the entrypoint starts as root only to give /app/media to `app`
# (Docker volumes are root-owned), then drops privileges with setpriv before running anything.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS prod
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY requirements/ /tmp/requirements/
RUN pip install -r /tmp/requirements/prod.txt
COPY --chown=app:app . /app
COPY docker/django/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/media && chown app:app /app/media \
    && DJANGO_SETTINGS_MODULE=config.settings.build python manage.py collectstatic --noinput
# Entrypoint drops to `app` after fixing volume ownership (see entrypoint.sh).
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
