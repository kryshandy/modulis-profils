"""Development worker: Huey consumer restarted automatically when the code changes.

Without it, the `worker` container keeps running stale code after an edit while `web` reloads, and the
two can disagree on a task signature (seen on 2026-11-11: an OTP task received a cache key as code).
Production keeps the plain `run_huey` command (deployments restart every process).
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import autoreload


class Command(BaseCommand):
    help = "Lance le worker Huey avec rechargement automatique (développement uniquement)."

    def handle(self, *args, **options):
        autoreload.run_with_reloader(call_command, "run_huey")
