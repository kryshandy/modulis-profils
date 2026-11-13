"""Evaluation super-admin with a FIXED password, meant to be deleted before going live.

    python manage.py bootstrap_superadmin           (or `make superadmin` with Docker)
    python manage.py bootstrap_superadmin --delete  (removes it; needs another active superuser)

Phone and password come from the environment (.env, never versioned): BOOTSTRAP_ADMIN_PHONE and
BOOTSTRAP_ADMIN_PASSWORD (32 characters minimum). Running the command again is idempotent: it
recreates the account if needed and puts the fixed password back, so the evaluator can always log in.
Two-factor authentication stays mandatory (enrolment at the first login), like every staff account.
In production, the system check security.W101 reminds that this account still exists.
"""

from __future__ import annotations

import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import services
from apps.accounts.models import User
from apps.platform import services as platform

PHONE_ENV = "BOOTSTRAP_ADMIN_PHONE"
PASSWORD_ENV = "BOOTSTRAP_ADMIN_PASSWORD"  # noqa: S105 - variable name, not a secret
MIN_LENGTH = 32
FULL_NAME = "Super-admin d'évaluation (à supprimer avant la mise en ligne)"


def bootstrap_phone() -> str:
    raw = os.environ.get(PHONE_ENV, "").strip()
    return services.normalize_phone(raw) if raw else ""


class Command(BaseCommand):
    help = "Crée (ou remet à son mot de passe fixe) le super-admin d'évaluation, ou le supprime (--delete)."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Supprime le super-admin d'évaluation.")

    def handle(self, *args, **options):
        try:
            phone = bootstrap_phone()
        except services.OTPError as exc:
            raise CommandError(f"{PHONE_ENV} invalide : {exc}") from exc
        if not phone:
            raise CommandError(f"Définissez {PHONE_ENV} dans .env (ex. +237600000000).")
        if options["delete"]:
            return self._delete(phone)
        password = os.environ.get(PASSWORD_ENV, "")
        if len(password) < MIN_LENGTH:
            raise CommandError(f"{PASSWORD_ENV} doit contenir au moins {MIN_LENGTH} caractères (dans .env).")
        user = User.objects.filter(phone=phone).first()
        try:
            validate_password(password, user=user or User(phone=phone, full_name=FULL_NAME))
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        with transaction.atomic():
            if user is None:
                user = User.objects.create_superuser(phone, password, full_name=FULL_NAME)
                action = "créé"
            else:
                if not user.is_staff and user.profiles.exists():
                    raise CommandError(f"{phone} est le compte d'un pro : choisissez un autre numéro.")
                user.set_password(password)
                user.is_staff = user.is_superuser = user.is_active = True
                user.full_name = user.full_name or FULL_NAME
                user.save()
                action = "remis au mot de passe fixe"
            platform.audit(None, "user.bootstrap_superadmin", phone, result=action)
        self.stdout.write(self.style.SUCCESS(f"Super-admin d'évaluation {phone} {action}."))
        self.stdout.write("Mot de passe : celui de BOOTSTRAP_ADMIN_PASSWORD dans .env (jamais affiché ici).")
        self.stdout.write("1re connexion : la double authentification (application TOTP) sera demandée.")

    def _delete(self, phone: str):
        user = User.objects.filter(phone=phone, is_superuser=True).first()
        if user is None:
            self.stdout.write("Aucun super-admin d'évaluation à supprimer.")
            return
        others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
        if not others.exists():
            raise CommandError("Créez d'abord un autre super-admin (make admin) : ce serait le dernier.")
        user.delete()
        platform.audit(None, "user.delete", phone, via="bootstrap_superadmin --delete")
        self.stdout.write(self.style.SUCCESS(f"Super-admin d'évaluation {phone} supprimé."))
