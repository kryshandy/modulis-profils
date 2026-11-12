"""2026 art direction of the catalogue: six premium layouts, self-hosted display fonts, curated palettes.

Layout keys are unchanged (only their labels): Signature (cover_color), Studio (split_photo), Éditorial
(editorial), Bento (centered), Vitrine (magazine), Carte (card). The contact block closes every page. Every theme gets a new layout, font pair,
palette and presets; premium flags are kept. Pages whose settings are still exactly the previous theme
defaults (never customised) follow the new defaults; customised pages keep their own choices.
"""

import importlib

from django.db import migrations, models

ALL = ["about", "services", "gallery", "hours", "area", "links", "contact"]
LAYOUT_CHOICES = [
    ("split_photo", "Studio — colonne image fixe"),
    ("cover_color", "Signature — typographie XXL"),
    ("centered", "Bento — grille de tuiles"),
    ("card", "Carte — luxe épuré"),
    ("editorial", "Éditorial — serif magazine"),
    ("magazine", "Vitrine — grande image"),
]


def pal(primary, accent, background, surface, text, name=""):
    data = {"primary": primary, "accent": accent, "background": background, "surface": surface, "text": text}
    if name:
        data["name"] = name
    return data


THEMES = {
    "signature": {
        "layout": "cover_color",
        "font_pair": "archivo",
        "corners": "rounded",
        "description": "Le style Modulis : titre géant en Archivo, composition de couleurs, bandeau défilant de "
        "tes prestations. Fort, lisible, chaleureux : pour tous les métiers.",
        "palette": pal("#0A7F7D", "#FD6552", "#EEF4F3", "#FFFFFF", "#16242C"),
        "presets": [
            pal("#0A7F7D", "#FD6552", "#EEF4F3", "#FFFFFF", "#16242C", "Sarcelle & corail"),
            pal("#16242C", "#17BDBB", "#EEF4F3", "#FFFFFF", "#16242C", "Encre & turquoise"),
            pal("#17BDBB", "#FD6552", "#062224", "#0B3133", "#EEF4F3", "Nuit"),
        ],
        "sections": ALL,
    },
    "boutique": {
        "layout": "cover_color",
        "font_pair": "archivo",
        "corners": "rounded",
        "description": "Énergique et pop : outremer et safran, gros titres, prix bien visibles et bandeau "
        "défilant de tes produits. Pour boutiques, marchés et commerces de quartier.",
        "palette": pal("#2B3FD6", "#FFB81C", "#F6F3EC", "#FFFFFF", "#15172A"),
        "presets": [
            pal("#2B3FD6", "#FFB81C", "#F6F3EC", "#FFFFFF", "#15172A", "Outremer & safran"),
            pal("#E4572E", "#2B3FD6", "#FBF4EC", "#FFFFFF", "#24140D", "Piment"),
            pal("#0F6B4F", "#FF8FA3", "#F3F5EF", "#FFFFFF", "#10221B", "Menthe & rose"),
        ],
        "sections": ["services", "about", "gallery", "hours", "area", "links", "contact"],
    },
    "horizon": {
        "layout": "split_photo",
        "font_pair": "archivo",
        "corners": "soft",
        "description": "Studio : ta photo (ou une composition graphique) reste fixe pendant que la page défile. "
        "Cobalt et sable, très net : idéal pour inspirer confiance au premier regard.",
        "palette": pal("#1D3FD8", "#FF8A3D", "#F4F1EA", "#FFFFFF", "#10131F"),
        "presets": [
            pal("#1D3FD8", "#FF8A3D", "#F4F1EA", "#FFFFFF", "#10131F", "Cobalt & sable"),
            pal("#0E6E68", "#F2B134", "#F1F4F1", "#FFFFFF", "#0F1F1E", "Lagune"),
            pal("#FF8A3D", "#1D3FD8", "#14161F", "#1D2030", "#F3F1EC", "Nuit orange"),
        ],
        "sections": ALL,
    },
    "chantier": {
        "layout": "split_photo",
        "font_pair": "archivo",
        "corners": "sharp",
        "description": "Robuste et architectural : acier, orange sécurité, grille de plan. Tes prestations et "
        "tes chantiers en premier, le bouton devis toujours à portée.",
        "palette": pal("#1F3A5F", "#FF7A1A", "#EDEBE6", "#FFFFFF", "#14181F"),
        "presets": [
            pal("#1F3A5F", "#FF7A1A", "#EDEBE6", "#FFFFFF", "#14181F", "Acier & sécurité"),
            pal("#2E2E2B", "#F5C400", "#EFEDE6", "#FFFFFF", "#1A1A18", "Bitume & jaune"),
            pal("#8A3B22", "#E9B44C", "#F3EEE7", "#FFFFFF", "#221812", "Latérite"),
        ],
        "sections": ["services", "gallery", "about", "area", "hours", "links", "contact"],
    },
    "eclat": {
        "layout": "card",
        "font_pair": "instrument",
        "corners": "rounded",
        "description": "Carte de luxe épurée : serif Instrument, bois de rose et blush, beaucoup d'air. Pour "
        "coiffure, esthétique, onglerie et bien-être.",
        "palette": pal("#8E3B4F", "#E9C3B3", "#F8F1EC", "#FFFFFF", "#2A1B1F"),
        "presets": [
            pal("#8E3B4F", "#E9C3B3", "#F8F1EC", "#FFFFFF", "#2A1B1F", "Bois de rose"),
            pal("#5D4A8A", "#E4CFE8", "#F6F3F9", "#FFFFFF", "#211A2E", "Lilas"),
            pal("#9A6B3F", "#EAD3B5", "#FAF5EE", "#FFFFFF", "#2A1F15", "Karité"),
        ],
        "sections": ["about", "services", "gallery", "hours", "area", "links", "contact"],
    },
    "saveur": {
        "layout": "magazine",
        "font_pair": "fraunces",
        "corners": "soft",
        "description": "Vitrine gourmande : grande image, étiquette prix, serif Fraunces façon menu, paprika "
        "et safran. Ta carte, tes horaires et la réservation en un coup d'œil.",
        "palette": pal("#B23A1E", "#F2C14E", "#F7F0E4", "#FFFBF4", "#2A160E"),
        "presets": [
            pal("#B23A1E", "#F2C14E", "#F7F0E4", "#FFFBF4", "#2A160E", "Paprika & safran"),
            pal("#2F5D3A", "#E9A23B", "#F4F1E6", "#FFFFFF", "#1A2419", "Feuille de manioc"),
            pal("#F2C14E", "#E4572E", "#16100C", "#211812", "#F6EEE3", "Braise"),
        ],
        "sections": ["services", "gallery", "about", "hours", "area", "links", "contact"],
    },
    "atelier": {
        "layout": "editorial",
        "font_pair": "fraunces",
        "corners": "sharp",
        "description": "Éditorial couture : grand serif Fraunces, filets, portrait en arche, liste de prix "
        "comme un lookbook. Ivoire et rouille. Pour couturiers et créateurs.",
        "palette": pal("#1A1714", "#B5562E", "#F3EEE6", "#FBF8F3", "#1A1714"),
        "presets": [
            pal("#1A1714", "#B5562E", "#F3EEE6", "#FBF8F3", "#1A1714", "Ivoire & rouille"),
            pal("#5B1F2E", "#C9A15B", "#F5EFEA", "#FFFFFF", "#221418", "Bordeaux"),
            pal("#E9DCC9", "#B5562E", "#141210", "#1D1A17", "#F1EBE2", "Noir couture"),
        ],
        "sections": ["about", "gallery", "services", "area", "hours", "links", "contact"],
    },
    "code": {
        "layout": "centered",
        "font_pair": "bricolage",
        "corners": "soft",
        "description": "Bento sombre : tuiles, indigo électrique et vert acide, typographie Bricolage. La page "
        "des développeurs, designers et freelances du numérique.",
        "palette": pal("#6D5DF6", "#B8F35A", "#0C0E14", "#151823", "#ECEEF5"),
        "presets": [
            pal("#6D5DF6", "#B8F35A", "#0C0E14", "#151823", "#ECEEF5", "Indigo & acide"),
            pal("#2DD4BF", "#F472B6", "#0A1214", "#111C1F", "#E6F2F1", "Terminal"),
            pal("#4F46E5", "#FF6B4A", "#F4F4F7", "#FFFFFF", "#12121C", "Clair"),
        ],
        "sections": ["about", "services", "gallery", "links", "hours", "area", "contact"],
    },
    "serenite": {
        "layout": "centered",
        "font_pair": "bricolage",
        "corners": "rounded",
        "description": "Bento apaisant : eau et pêche, tuiles arrondies, statut « Ouvert maintenant » et horaires "
        "en avant. Pour cabinets de santé, kinés et praticiens.",
        "palette": pal("#1F6F78", "#F2B8A2", "#F1F5F3", "#FFFFFF", "#13282B"),
        "presets": [
            pal("#1F6F78", "#F2B8A2", "#F1F5F3", "#FFFFFF", "#13282B", "Eau & pêche"),
            pal("#3A6EA5", "#A7D7C5", "#F2F6FA", "#FFFFFF", "#142235", "Azur"),
            pal("#5E7D4E", "#E8C77E", "#F4F5EF", "#FFFFFF", "#1C2418", "Sauge"),
        ],
        "sections": ["about", "services", "hours", "area", "gallery", "links", "contact"],
    },
    "cabinet": {
        "layout": "editorial",
        "font_pair": "fraunces",
        "corners": "sharp",
        "description": "Institutionnel et raffiné : marine profond, laiton, serif Fraunces, domaines présentés "
        "comme un sommaire. Pour avocats, notaires, comptables et consultants.",
        "palette": pal("#14284B", "#A8834A", "#F5F2EC", "#FFFFFF", "#141B2B"),
        "presets": [
            pal("#14284B", "#A8834A", "#F5F2EC", "#FFFFFF", "#141B2B", "Marine & laiton"),
            pal("#2B2B2B", "#8F7448", "#F4F3F0", "#FFFFFF", "#1C1C1C", "Graphite"),
            pal("#1E4636", "#B9975B", "#F2F3EE", "#FFFFFF", "#15231C", "Vert anglais"),
        ],
        "sections": ["about", "services", "area", "hours", "links", "gallery", "contact"],
    },
    "objectif": {
        "layout": "magazine",
        "font_pair": "archivo",
        "corners": "sharp",
        "description": "Vitrine plein contraste : fond noir, grande image cadrée, accent corail et bandeau "
        "défilant. Ton portfolio d'abord : photographes, vidéastes, événementiel.",
        "palette": pal("#F25C3B", "#EDE6DA", "#0D0D0F", "#17171A", "#F2F0EC"),
        "presets": [
            pal("#F25C3B", "#EDE6DA", "#0D0D0F", "#17171A", "#F2F0EC", "Noir & corail"),
            pal("#E9C46A", "#F2F0EC", "#0F1012", "#1A1B1F", "#F2F2EE", "Noir doré"),
            pal("#111111", "#F25C3B", "#F4F2EE", "#FFFFFF", "#111111", "Galerie blanche"),
        ],
        "sections": ["gallery", "about", "services", "area", "hours", "links", "contact"],
    },
    "savoir": {
        "layout": "centered",
        "font_pair": "bricolage",
        "corners": "rounded",
        "description": "Bento vivant : indigo et soleil, tuiles arrondies, chiffres clés. Pour enseignants, "
        "répétiteurs, coachs et centres de formation.",
        "palette": pal("#4433D6", "#FFC53D", "#F4F2FB", "#FFFFFF", "#18162B"),
        "presets": [
            pal("#4433D6", "#FFC53D", "#F4F2FB", "#FFFFFF", "#18162B", "Indigo & soleil"),
            pal("#0B7A75", "#FF7A59", "#F1F6F5", "#FFFFFF", "#0F2221", "Océan"),
            pal("#C2185B", "#FFD54F", "#FBF3F6", "#FFFFFF", "#2A1020", "Framboise"),
        ],
        "sections": ["about", "services", "hours", "area", "gallery", "links", "contact"],
    },
    "prestige": {
        "layout": "card",
        "font_pair": "instrument",
        "corners": "soft",
        "description": "Carte de prestige : nuit profonde, or champagne, serif Instrument et filets. Pour les "
        "métiers qui misent sur l'excellence et le sur-mesure.",
        "palette": pal("#C9A45C", "#E8DCC2", "#0F1215", "#171B20", "#EEE8DE"),
        "presets": [
            pal("#C9A45C", "#E8DCC2", "#0F1215", "#171B20", "#EEE8DE", "Nuit champagne"),
            pal("#B4865B", "#E9D8C4", "#15110E", "#1E1915", "#F1E9DF", "Cuir"),
            pal("#1C1C1C", "#C9A45C", "#F7F5F0", "#FFFFFF", "#1C1C1C", "Ivoire & or"),
        ],
        "sections": ALL,
    },
}


def _upper(palette: dict) -> dict:
    return {k: str(v).upper() for k, v in (palette or {}).items() if k != "name"}


def apply(apps, schema_editor):
    Theme = apps.get_model("themes", "Theme")
    ProfileTheme = apps.get_model("themes", "ProfileTheme")
    previous = {t["code"]: t for t in importlib.import_module("apps.themes.migrations.0002_seed_themes").THEMES}
    for code, data in THEMES.items():
        theme = Theme.objects.filter(code=code).first()
        if theme is None:
            continue
        theme.layout = data["layout"]
        theme.font_pair = data["font_pair"]
        theme.corners = data["corners"]
        theme.description = data["description"]
        theme.palette = data["palette"]
        theme.palette_presets = data["presets"]
        theme.sections = data["sections"]
        theme.save()
        old = previous.get(code)
        if not old:
            continue
        # Untouched pages (still exactly on the previous defaults) follow the new art direction.
        for pt in ProfileTheme.objects.filter(theme=theme):
            fields = []
            if pt.hero_variant == old["layout"]:
                pt.hero_variant = data["layout"]
                fields.append("hero_variant")
            if pt.font_pair == old["font_pair"]:
                pt.font_pair = data["font_pair"]
                fields.append("font_pair")
            if pt.corners == old["corners"]:
                pt.corners = data["corners"]
                fields.append("corners")
            if _upper(pt.palette) == _upper(old["palette"]):
                pt.palette = _upper(data["palette"])
                fields.append("palette")
            if fields:
                pt.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("themes", "0003_premium_themes_entitlement")]

    operations = [
        migrations.AlterField(
            model_name="profiletheme",
            name="hero_variant",
            field=models.CharField(blank=True, choices=LAYOUT_CHOICES, max_length=16, verbose_name="en-tête"),
        ),
        migrations.AlterField(
            model_name="theme",
            name="layout",
            field=models.CharField(
                choices=LAYOUT_CHOICES, default="cover_color", max_length=16, verbose_name="mise en page"
            ),
        ),
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
