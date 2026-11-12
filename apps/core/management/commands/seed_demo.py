"""Demo data for local development: fictitious pros, a card batch and a staff account.

Usage: make seed-demo   (or: docker compose exec web python manage.py seed_demo)
Never run in production: refuses when DEBUG is False unless --force.

The showcase pages (one per site layout) get realistic but entirely fictitious content: names, phone
numbers (+23769000010x), e-mails on exemple.test, prices in FCFA, opening hours, and generated abstract
visuals in the theme palette (no real photo of anyone). Running the command again refreshes them.
"""

import io
import math
import random
import secrets

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from apps.accounts.models import User
from apps.cards.services import create_batch
from apps.core.models import City, Trade
from apps.profiles import services as profiles
from apps.themes import services as themes
from apps.themes.models import Theme

WEEKDAYS = ("mo", "tu", "we", "th", "fr")


def hours(days, start, end, **extra):
    data = {day: [[start, end]] for day in days}
    data.update(extra)
    return data


SHOWCASE = [
    {
        "phone": "+237690000101",
        "name": "Ange Kenmogne",
        "trade": "plombier",
        "city": "douala",
        "feminine": False,
        "theme": "signature",
        "photo": True,
        "fields": {
            "district": "Bonapriso",
            "service_area": "Akwa, Bonapriso, Bonamoussadi, Makepe, Kotto",
            "address": "Rue Joss, face pharmacie du Centre",
            "email_public": "ange.kenmogne@exemple.test",
            "latitude": "4.048300",
            "longitude": "9.704300",
            "opening_hours": hours((*WEEKDAYS, "sa"), "08:00", "18:00", su=[["09:00", "13:00"]]),
            "price_range": "5 000–150 000 FCFA",
        },
        "bio": "Plombier à Douala depuis 2012, j'interviens en moins de deux heures pour les fuites, les "
        "débouchages et les pannes de chauffe-eau. Devis gratuit sur place, travail soigné et garanti six mois, "
        "pièces de qualité achetées avec vous.\n\nJe rénove aussi les salles de bain de A à Z : douche à "
        "l'italienne, carrelage, robinetterie et évacuations. Urgences le dimanche matin.",
        "services": [
            ("Réparation de fuites", "Diagnostic et réparation en moins de 2 h, partout à Douala.", "dès 5 000 FCFA"),
            (
                "Pose de chauffe-eau",
                "Électrique ou solaire, toutes marques, mise en service incluse.",
                "dès 25 000 FCFA",
            ),
            ("Débouchage", "Éviers, douches, WC et regards, sans casse.", "dès 10 000 FCFA"),
            ("Salle de bain clé en main", "Plan, carrelage, sanitaires et finitions.", "sur devis"),
        ],
        "gallery": [
            "Salle de bain rénovée à Bonapriso",
            "Pose d'un chauffe-eau solaire à Makepe",
            "Nouvelle robinetterie dans une cuisine d'Akwa",
            "Douche à l'italienne, finitions carrelage",
        ],
        "links": [("website", "https://exemple.test/ange-kenmogne"), ("facebook", "https://exemple.test/fb/ange")],
    },
    {
        "phone": "+237690000102",
        "name": "Brenda Atangana",
        "trade": "couturier",
        "city": "yaounde",
        "feminine": True,
        "theme": "atelier",
        "photo": False,
        "fields": {
            "district": "Bastos",
            "service_area": "Yaoundé et livraison dans tout le Cameroun",
            "email_public": "atelier.brenda@exemple.test",
            "opening_hours": hours(WEEKDAYS, "09:00", "18:30", sa=[["10:00", "16:00"]]),
            "price_range": "5 000–250 000 FCFA",
        },
        "bio": "Couturière à Yaoundé, je dessine et je couds des tenues sur mesure qui vous ressemblent. "
        "Pagne, kaba, robes de soirée et tenues de mariage : chaque pièce est coupée à la main dans mon atelier "
        "de Bastos, avec des finitions soignées.\n\nEssayages sur rendez-vous, conseils de style et livraison "
        "dans tout le Cameroun. Commandes groupées pour cérémonies et uniformes d'entreprise.",
        "services": [
            ("Tenue sur mesure en pagne", "Prise de mesures, deux essayages, finitions main.", "dès 15 000 FCFA"),
            ("Robe de soirée", "Création unique, tissus sélectionnés avec vous.", "dès 60 000 FCFA"),
            ("Tenue de mariage", "Robe ou kaba de cérémonie, accompagnement complet.", "dès 150 000 FCFA"),
            ("Retouches", "Ourlets, ajustements, fermetures, en 48 h.", "dès 2 000 FCFA"),
            ("Uniformes d'entreprise", "Séries de 10 à 200 pièces, délais garantis.", "sur devis"),
        ],
        "gallery": [
            "Robe de soirée en wax, collection Saison sèche",
            "Kaba brodé pour une cérémonie à Bastos",
            "Ensemble pagne pour homme",
            "Détail de finitions faites main",
            "Essayage à l'atelier",
        ],
        "links": [("instagram", "https://exemple.test/ig/atelier-brenda")],
    },
    {
        "phone": "+237690000103",
        "name": "Kevin Ndjock",
        "trade": "developpeur",
        "city": "douala",
        "feminine": False,
        "theme": "code",
        "photo": True,
        "fields": {
            "district": "Akwa",
            "service_area": "Douala, Yaoundé et à distance",
            "email_public": "kevin.ndjock@exemple.test",
            "opening_hours": hours(WEEKDAYS, "08:30", "17:30"),
            "price_range": "150 000–2 500 000 FCFA",
        },
        "bio": "Développeur web freelance basé à Douala, je crée des sites rapides et des outils simples pour les "
        "PME camerounaises. Six ans d'expérience en Python et JavaScript, paiement Mobile Money intégré, "
        "accompagnement de A à Z.\n\nJe forme aussi vos équipes et j'assure la maintenance mensuelle, avec un "
        "interlocuteur unique qui répond sur WhatsApp.",
        "services": [
            ("Site vitrine", "Rapide, bien référencé, livré en 2 semaines.", "dès 250 000 FCFA"),
            ("Boutique en ligne", "Orange Money et MTN MoMo, gestion des stocks.", "dès 600 000 FCFA"),
            ("Application de gestion", "Ventes, clients, factures : sur mesure.", "sur devis"),
            ("Maintenance", "Mises à jour, sauvegardes, assistance.", "35 000 FCFA / mois"),
        ],
        "gallery": ["Tableau de bord d'une PME de Bonabéri", "Boutique en ligne d'une marque de cosmétiques"],
        "links": [("website", "https://exemple.test/kevin-dev"), ("linkedin", "https://exemple.test/in/kevin")],
    },
    {
        "phone": "+237690000105",
        "name": "Chez Mama Ngono",
        "trade": "traiteur",
        "city": "yaounde",
        "feminine": True,
        "theme": "saveur",
        "photo": True,
        "fields": {
            "district": "Bastos",
            "service_area": "Livraison à Yaoundé",
            "address": "Carrefour Bastos, à côté de la boulangerie",
            "email_public": "mama.ngono@exemple.test",
            "opening_hours": hours((*WEEKDAYS, "sa"), "11:00", "22:00", su=[["12:00", "17:00"]]),
            "price_range": "2 500–25 000 FCFA",
        },
        "bio": "Cuisine camerounaise faite maison, comme à la maison : ndolè, poulet DG, poisson braisé et "
        "mets de pistache préparés chaque matin avec des produits du marché.\n\nSur place, à emporter ou livré "
        "chez vous à Yaoundé. Nous cuisinons aussi pour vos mariages, baptêmes et réunions d'entreprise.",
        "services": [
            ("Ndolè complet", "Crevettes, viande, plantain mûr ou miondo.", "3 500 FCFA"),
            ("Poulet DG", "Le classique du dimanche, légumes croquants.", "5 000 FCFA"),
            ("Poisson braisé", "Bar ou carpe, sauce maison, bâtons de manioc.", "dès 4 500 FCFA"),
            ("Formule traiteur", "Buffet pour 20 à 300 invités, service inclus.", "dès 6 000 FCFA / pers."),
        ],
        "gallery": [
            "Le ndolè du jour",
            "Poisson braisé et bâtons de manioc",
            "Buffet pour un mariage à Mvan",
            "La salle, carrefour Bastos",
            "Jus de foléré et de gingembre maison",
            "Poulet DG",
        ],
        "links": [("facebook", "https://exemple.test/fb/mama-ngono")],
    },
    {
        "phone": "+237690000106",
        "name": "Fotso Bâtiment",
        "trade": "macon",
        "city": "bafoussam",
        "feminine": False,
        "theme": "chantier",
        "photo": False,
        "fields": {
            "district": "Tamdja",
            "service_area": "Bafoussam, Dschang, Mbouda et environs",
            "email_public": "fotso.batiment@exemple.test",
            "opening_hours": hours((*WEEKDAYS, "sa"), "07:00", "17:00"),
            "price_range": "50 000–15 000 000 FCFA",
        },
        "bio": "Entreprise de maçonnerie à Bafoussam depuis 2009 : fondations, élévation, dalles et "
        "finitions. Une équipe de huit ouvriers qualifiés, un chef de chantier présent chaque jour.\n\nNous "
        "établissons un devis détaillé gratuit, un planning clair et des photos d'avancement envoyées sur "
        "WhatsApp chaque semaine.",
        "services": [
            ("Construction de maison", "Des fondations à la toiture, clé en main.", "sur devis"),
            ("Dalle et chaînages", "Béton dosé, ferraillage contrôlé.", "dès 18 000 FCFA / m²"),
            ("Clôture et portail", "Parpaings, crépi, pose du portail.", "dès 25 000 FCFA / ml"),
            ("Carrelage et finitions", "Sols, murs, terrasses.", "dès 6 000 FCFA / m²"),
        ],
        "gallery": ["Villa R+1 à Tamdja", "Dalle coulée à Dschang", "Clôture et portail à Mbouda"],
        "links": [],
    },
    {
        "phone": "+237690000107",
        "name": "Mireille Eboa",
        "trade": "coiffeur",
        "city": "douala",
        "feminine": True,
        "theme": "eclat",
        "photo": True,
        "fields": {
            "district": "Bonamoussadi",
            "service_area": "Au salon ou à domicile à Douala",
            "address": "Bonamoussadi, carrefour Kotto",
            "email_public": "mireille.eboa@exemple.test",
            "opening_hours": hours(("tu", "we", "th", "fr", "sa"), "09:00", "19:00", su=[["10:00", "15:00"]]),
            "price_range": "3 000–45 000 FCFA",
        },
        "bio": "Coiffeuse et soins du cheveu naturel à Douala, je prends le temps d'écouter avant de coiffer. "
        "Tresses, nattes collées, vanilles, soins profonds et coiffures de mariée, avec des produits doux "
        "adaptés à vos cheveux.\n\nRendez-vous au salon de Bonamoussadi ou à domicile. Un thé vous attend.",
        "services": [
            ("Tresses et nattes collées", "Toutes longueurs, mèches fournies sur demande.", "dès 8 000 FCFA"),
            ("Soin profond cheveux naturels", "Bain d'huile, masque, démêlage doux.", "12 000 FCFA"),
            ("Coiffure de mariée", "Essai inclus, déplacement le jour J.", "dès 45 000 FCFA"),
            ("Brushing et mise en plis", "", "3 000 FCFA"),
        ],
        "gallery": ["Nattes collées et perles", "Coiffure de mariée", "Le salon de Bonamoussadi"],
        "links": [("instagram", "https://exemple.test/ig/mireille-coiffure")],
    },
    {
        "phone": "+237690000108",
        "name": "Studio Lumière Kribi",
        "trade": "photographe",
        "city": "kribi",
        "feminine": False,
        "theme": "objectif",
        "photo": False,
        "fields": {
            "district": "Mpangou",
            "service_area": "Kribi, Douala, Yaoundé et tout le Cameroun",
            "email_public": "studio.lumiere@exemple.test",
            "opening_hours": hours((*WEEKDAYS, "sa"), "09:00", "18:00"),
            "price_range": "25 000–900 000 FCFA",
        },
        "bio": "Photographe et vidéaste à Kribi, je raconte vos mariages, vos événements et vos marques avec "
        "une image lumineuse et naturelle. Reportages sur la plage, en studio ou sur site.\n\nGalerie privée en "
        "ligne sous dix jours, tirages d'art et films courts pour vos réseaux sociaux.",
        "services": [
            ("Mariage, journée complète", "Préparatifs, cérémonie, soirée, 400 photos.", "dès 450 000 FCFA"),
            ("Séance portrait", "1 h en extérieur, 20 photos retouchées.", "35 000 FCFA"),
            ("Film d'entreprise", "Tournage, montage, version réseaux sociaux.", "sur devis"),
        ],
        "gallery": [
            "Mariage au coucher du soleil, plage de Kribi",
            "Portrait en studio",
            "Chutes de la Lobé",
            "Campagne pour une marque de boissons",
            "Baptême à Mpangou",
        ],
        "links": [("instagram", "https://exemple.test/ig/studio-lumiere")],
    },
]
INCOMPLETE = ("+237690000104", "Salon Belle Allure", "coiffeur", "douala", True)  # incomplete on purpose


# --- generated visuals (abstract compositions in the theme palette, never a real person) -----------


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def artwork(palette: dict, seed: str, size: tuple[int, int]) -> bytes:
    """A calm, editorial composition: gradient field, arch, sun, rings, bands and a little grain."""
    rng = random.Random(seed)  # noqa: S311 - deterministic demo artwork, not security
    scale = 2
    w, h = size[0] * scale, size[1] * scale
    primary, accent = _rgb(palette["primary"]), _rgb(palette["accent"])
    bg, text = _rgb(palette["background"]), _rgb(palette["text"])
    deep = _mix(primary, (0, 0, 0), 0.35)
    top, bottom = rng.choice([(bg, _mix(bg, accent, 0.35)), (primary, deep), (_mix(bg, primary, 0.15), bg)])
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    for y in range(0, h, 4):
        draw.rectangle([0, y, w, y + 4], fill=_mix(top, bottom, y / h))
    on_dark = sum(top) < 330
    # horizon bands
    base = h * rng.uniform(0.58, 0.72)
    for i, colour in enumerate((_mix(primary, bg, 0.25), primary, deep)):
        y0 = base + i * h * 0.09
        amp, freq = h * rng.uniform(0.02, 0.06), rng.uniform(1.2, 2.4)
        points = [(x, y0 + amp * math.sin(x / w * math.pi * freq + i)) for x in range(0, w + 8, 8)]
        draw.polygon([*points, (w, h), (0, h)], fill=colour)
    # sun
    r = min(w, h) * rng.uniform(0.16, 0.26)
    cx, cy = w * rng.uniform(0.25, 0.75), base - r * rng.uniform(0.2, 0.9)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    # arch
    aw = w * rng.uniform(0.22, 0.32)
    ax = rng.choice([w * 0.08, w * 0.92 - aw])
    ah = h * rng.uniform(0.34, 0.48)
    ay = base + h * 0.12 - ah
    arch = _mix(_mix(accent, bg, 0.55), (255, 255, 255), 0.25 if not on_dark else 0)
    draw.rounded_rectangle([ax, ay, ax + aw, ay + ah + aw], radius=int(aw / 2), fill=arch)
    # rings and dots
    ring = _mix(text, top, 0.55) if not on_dark else _mix((255, 255, 255), top, 0.5)
    for _ring in range(rng.randint(1, 2)):
        rr = min(w, h) * rng.uniform(0.25, 0.45)
        rx, ry = w * rng.uniform(0.1, 0.9), h * rng.uniform(0.1, 0.5)
        draw.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], outline=ring, width=3 * scale)
    step = 26 * scale
    gx, gy = w * rng.uniform(0.55, 0.8), h * 0.08
    for i in range(6):
        for j in range(6):
            x, y = gx + i * step, gy + j * step
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=ring)
    img = img.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(0.4))
    noise = Image.effect_noise(size, 10).convert("RGB")
    img = Image.blend(img, noise, 0.035)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def upload(name: str, data: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type="image/jpeg")


class Command(BaseCommand):
    help = "Crée des données de démonstration (profils fictifs, pages vitrines, lot de cartes, compte admin)."

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

        for demo in SHOWCASE:
            profile = self.showcase(demo)
            state = "indexable" if profile.is_indexable else "non indexable"
            self.stdout.write(f"  /{profile.slug}  [{demo['theme']}]  ({profile.completeness_score} %, {state})")

        phone, name, trade_slug, city_slug, feminine = INCOMPLETE
        _user, profile, created = profiles.get_or_create_profile(
            phone,
            name,
            trade=Trade.objects.filter(slug=trade_slug).first(),
            city=City.objects.filter(slug=city_slug).first(),
        )
        if created:
            profiles.update_profile(profile, is_feminine=feminine)
        self.stdout.write(f"  /{profile.slug}  (incomplet, volontairement)")

        _batch, pairs = create_batch(f"DEMO-{timezone.now():%Y%m%d-%H%M%S}", options["cards"])  # rerunnable
        self.stdout.write(self.style.SUCCESS("Cartes de démo (code public → code d'activation) :"))
        for public, activation in pairs:
            self.stdout.write(f"  {settings.SITE_URL}/c/{public}   activation : {activation}")

    def showcase(self, demo: dict):
        """Create the page if needed, then (re)write its showcase content through the profiles services."""
        trade = Trade.objects.filter(slug=demo["trade"]).first()
        city = City.objects.filter(slug=demo["city"]).first()
        _user, profile, _created = profiles.get_or_create_profile(demo["phone"], demo["name"], trade=trade, city=city)
        profiles.update_profile(profile, bio=demo["bio"], is_feminine=demo["feminine"], **demo["fields"])
        for service in list(profile.services.all()):
            profiles.delete_service(profile, service.pk)
        for title, desc, price in demo["services"]:
            profiles.add_service(profile, title, description=desc, price_label=price)
        for link in list(profile.links.all()):
            profiles.delete_link(profile, link.pk)
        for kind, url in demo["links"]:
            profiles.add_link(profile, kind, url)

        theme = Theme.objects.filter(code=demo["theme"]).first()
        palette = themes.clean_palette(theme.palette if theme else {})
        for media in list(profile.media.all()):
            profiles.delete_media(profile, media.pk)
        for index, caption in enumerate(demo["gallery"]):
            size = (1200, 900) if index % 3 != 1 else (900, 1200)
            data = artwork(palette, f"{demo['phone']}-g{index}", size)
            profiles.add_media(profile, upload(f"demo-{index}.jpg", data), caption=caption)
        if demo["photo"]:
            profiles.set_photo(profile, upload("demo-photo.jpg", artwork(palette, f"{demo['phone']}-p", (800, 1000))))
        else:
            profiles.remove_photo(profile)
        if theme is not None:
            themes.assign_theme(profile, theme)
        profile.refresh_from_db()
        return profile
