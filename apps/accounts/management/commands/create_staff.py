"""Create a Modulis staff account (admin access with password + mandatory TOTP 2FA).

Interactive:      python manage.py create_staff            (or `make admin` with Docker)
Non-interactive:  DJANGO_STAFF_PASSWORD=… python manage.py create_staff --phone +2376… \
                      --full-name "Awa Ndi" [--superuser] --no-input
The password is never accepted on the command line (shell history, process list).
"""

from __future__ import annotations

import getpass
import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts import services
from apps.accounts.models import User

PASSWORD_ENV = "DJANGO_STAFF_PASSWORD"  # noqa: S105 - variable name, not a secret
MAX_PASSWORD_TRIES = 3


class Command(BaseCommand):
    help = "Crée un compte de l'équipe Modulis (administration : mot de passe + double authentification)."

    def add_arguments(self, parser):
        parser.add_argument("--phone", help="Numéro de téléphone (E.164, ex. +237690000100).")
        parser.add_argument("--full-name", default=None, help="Nom complet.")
        parser.add_argument("--superuser", action="store_true", help="Super-administrateur (tous les droits).")
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_false",
            dest="interactive",
            help=f"Sans question : mot de passe lu dans la variable d'environnement {PASSWORD_ENV}.",
        )

    def handle(self, *args, phone=None, full_name=None, superuser=False, interactive=True, **options):
        phone = self._phone(phone, interactive)
        if full_name is None:
            full_name = input("Nom complet : ").strip() if interactive else ""
        if not superuser and interactive:
            superuser = input("Super-administrateur (tous les droits) ? [o/N] : ").strip().lower() in {"o", "oui", "y"}
        password = self._password(phone, full_name, interactive)
        try:
            user = services.create_staff_user(phone, password, full_name=full_name, superuser=superuser)
        except (services.OTPError, ValueError, ValidationError) as exc:
            raise CommandError(_message(exc)) from exc

        role = "super-administrateur" if user.is_superuser else "membre de l'équipe"
        admin_url = f"{settings.SITE_URL}/{settings.ADMIN_URL.lstrip('/')}"
        self.stdout.write(self.style.SUCCESS(f"Compte {role} créé : {user.phone}"))
        self.stdout.write(
            f"Étape suivante : connectez-vous à {admin_url} avec ce numéro et ce mot de passe, puis scannez "
            "le QR code avec une application d'authentification (Google Authenticator, Microsoft "
            "Authenticator, Aegis…). Notez les 10 codes de secours affichés ensuite."
        )
        if not user.is_superuser:
            self.stdout.write(
                "Ce compte n'a encore aucune permission : un super-administrateur doit lui attribuer un groupe "
                "dans l'administration (Utilisateurs > ce compte > Équipe Modulis)."
            )

    def _phone(self, phone: str | None, interactive: bool) -> str:
        if not phone:
            if not interactive:
                raise CommandError("--phone est obligatoire avec --no-input.")
            phone = input("Téléphone (ex. +237690000100) : ").strip()
        try:
            phone = services.normalize_phone(phone)
        except services.OTPError as exc:
            raise CommandError(str(exc)) from exc
        if User.objects.filter(phone=phone).exists():
            raise CommandError("Un compte existe déjà avec ce numéro.")
        return phone

    def _password(self, phone: str, full_name: str, interactive: bool) -> str:
        probe = User(phone=phone, full_name=full_name)
        if not interactive:
            password = os.environ.get(PASSWORD_ENV, "")
            if not password:
                raise CommandError(f"Définis la variable d'environnement {PASSWORD_ENV} avec --no-input.")
            return password
        for _ in range(MAX_PASSWORD_TRIES):
            password = getpass.getpass("Mot de passe (12 caractères minimum) : ")
            if password != getpass.getpass("Mot de passe (confirmation) : "):
                self.stderr.write("Les deux mots de passe ne correspondent pas.")
                continue
            try:
                validate_password(password, user=probe)
            except ValidationError as exc:
                self.stderr.write("\n".join(exc.messages))
                continue
            return password
        raise CommandError("Trop d'essais : aucun compte créé.")


def _message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc)
