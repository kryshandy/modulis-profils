"""Print a fresh IndexNow key to put in KLIZ_INDEXNOW_KEY (.env)."""

from django.core.management.base import BaseCommand
from kliz import IndexNowProvider


class Command(BaseCommand):
    help = "Génère une clé IndexNow (à placer dans KLIZ_INDEXNOW_KEY)."

    def add_arguments(self, parser):
        parser.add_argument("--length", type=int, default=32)

    def handle(self, *args, length: int, **options):
        self.stdout.write(IndexNowProvider.generate_key(length))
