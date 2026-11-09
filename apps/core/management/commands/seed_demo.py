"""Demo data for local development: fictitious pros, a card batch and a staff account.

Usage: make seed-demo   (or: docker compose exec web python manage.py seed_demo)
Never run in production: refuses when DEBUG is False unless --force.
"""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.cards.services import create_batch
from apps.core.models import City, Trade
from apps.profiles import services as profiles
from apps.profiles.models import ProfileService

DEMO = [
    # phone, name, trade slug, city slug, feminine, bio, services
    (
        "+237690000101",
        "Ange Kenmogne",
        "plombier",
        "douala",
        False,
        "Plombier à Douala depuis 2012, j'interviens rapidement à Akwa, Bonapriso, Bonamoussadi et Makepe pour les "
        "fuites, les débouchages, la pose de chauffe-eau et la rénovation de salles de bain. Devis gratuit sur place, "
        "travail soigné et garanti, pièces de qualité. Disponible du lundi au samedi, urgences le dimanche.",
        [("Réparation de fuites", "Intervention en moins de 2 h"), ("Pose de chauffe-eau", "Toutes marques")],
    ),
    (
        "+237690000102",
        "Brenda Atangana",
        "couturier",
        "yaounde",
        True,
        "Couturière à Yaoundé (quartier Bastos), je réalise des tenues sur mesure en pagne, kaba, robes de soirée et "
        "uniformes d'entreprise. Chaque modèle est cousu à la main avec des finitions soignées. Retouches rapides, "
        "conseils de style et livraison possible dans toute la ville. Commandes groupées pour mariages et cérémonies.",
        [("Tenue sur mesure", "dès 15 000 FCFA"), ("Retouches", "en 48 h"), ("Uniformes", "devis sur demande")],
    ),
    (
        "+237690000103",
        "Kevin Ndjock",
        "developpeur",
        "douala",
        False,
        "Développeur web freelance basé à Douala, je crée des sites vitrines rapides, des boutiques en ligne avec "
        "paiement Mobile Money et des applications de gestion pour les PME camerounaises. Six ans d'expérience en "
        "Python et JavaScript, accompagnement de A à Z, formation de vos équipes et maintenance mensuelle.",
        [("Site vitrine", "livré en 2 semaines"), ("Boutique en ligne", "Orange Money et MTN MoMo")],
    ),
    ("+237690000104", "Salon Belle Allure", "coiffeur", "douala", True, "", []),  # incomplete on purpose
]


class Command(BaseCommand):
    help = "Crée des données de démonstration (profils fictifs, lot de cartes, compte admin)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Autoriser hors DEBUG (déconseillé).")
        parser.add_argument("--cards", type=int, default=10, help="Nombre de cartes dans le lot de démo.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("seed_demo ne s'exécute qu'en DEBUG (ou avec --force).")

        admin_phone = "+237690000100"
        if not User.objects.filter(phone=admin_phone).exists():
            password = secrets.token_urlsafe(12)  # random, shown once: never a password in the code
            User.objects.create_superuser(admin_phone, password=password, full_name="Admin Démo")
            self.stdout.write(self.style.SUCCESS(f"Admin : {admin_phone} / {password}  (/{settings.ADMIN_URL})"))

        for phone, name, trade_slug, city_slug, feminine, bio, services in DEMO:
            trade = Trade.objects.filter(slug=trade_slug).first()
            city = City.objects.filter(slug=city_slug).first()
            _user, profile, created = profiles.get_or_create_profile(phone, name, trade=trade, city=city)
            if created:
                profile.bio = bio
                profile.is_feminine = feminine
                profile.save()
                for order, (title, desc) in enumerate(services):
                    ProfileService.objects.create(profile=profile, title=title, description=desc, order=order)
                profiles.refresh_seo_state(profile)
            profile.refresh_from_db()
            state = "indexable" if profile.is_indexable else "non indexable"
            self.stdout.write(f"  /{profile.slug}  ({profile.completeness_score} %, {state})")

        _batch, pairs = create_batch(f"DEMO-{User.objects.count():03d}", options["cards"])
        self.stdout.write(self.style.SUCCESS("Cartes de démo (code public → code d'activation) :"))
        for public, activation in pairs:
            self.stdout.write(f"  {settings.SITE_URL}/c/{public}   activation : {activation}")
