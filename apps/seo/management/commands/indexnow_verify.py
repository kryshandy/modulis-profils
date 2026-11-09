"""Check that the IndexNow key file is served the way search engines expect (network call)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from kliz import ProviderError

from apps.seo.notifier import indexnow_provider


class Command(BaseCommand):
    help = "Vérifie que le fichier de clé IndexNow est publié correctement (/<clé>.txt)."

    def handle(self, *args, **options):
        if not settings.KLIZ_INDEXNOW_KEY:
            raise CommandError("KLIZ_INDEXNOW_KEY n'est pas défini.")
        try:
            provider = indexnow_provider()
        except ValueError as exc:
            raise CommandError(f"Clé IndexNow invalide : {exc}") from exc
        try:
            location = provider.verify_key()
        except ProviderError as exc:
            raise CommandError(f"Échec de la vérification : {exc}") from exc
        finally:
            provider.close()
        self.stdout.write(self.style.SUCCESS(f"Clé IndexNow vérifiée : {location.replace(provider.api_key, '<clé>')}"))
