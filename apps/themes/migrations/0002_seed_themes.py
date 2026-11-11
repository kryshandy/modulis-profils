"""Seed the professional theme catalogue (one per category + Modulis Signature, the default).

Frozen data: later catalogue changes go in new migrations (or the admin), never here.
Sections: about, services, gallery, hours, area, links, contact.
"""

from django.db import migrations

ALL = ["about", "services", "gallery", "hours", "area", "links", "contact"]


def pal(primary, accent, background, surface, text, name=""):
    data = {"primary": primary, "accent": accent, "background": background, "surface": surface, "text": text}
    if name:
        data["name"] = name
    return data


THEMES = [
    {
        "code": "signature",
        "name": "Modulis Signature",
        "category": "universel",
        "layout": "cover_color",
        "description": "Le style Modulis : bandeau sarcelle, typographie Archivo, lisible et chaleureux. "
        "Parfait pour tous les métiers.",
        "palette": pal("#0A7F7D", "#FD6552", "#EEF4F3", "#FFFFFF", "#16242C"),
        "presets": [
            pal("#0A7F7D", "#FD6552", "#EEF4F3", "#FFFFFF", "#16242C", "Sarcelle"),
            pal("#075E5E", "#17BDBB", "#EEF4F3", "#FFFFFF", "#16242C", "Sarcelle profond"),
            pal("#17BDBB", "#FD6552", "#062224", "#0B3133", "#EEF4F3", "Nuit"),
        ],
        "font_pair": "archivo",
        "corners": "rounded",
        "sections": ALL,
        "cta_label": "Écrire sur WhatsApp",
        "premium": False,
    },
    {
        "code": "horizon",
        "name": "Horizon",
        "category": "universel",
        "layout": "split_photo",
        "description": "Grande photo à côté de ton nom, bleu cobalt énergique : idéal pour inspirer confiance "
        "au premier regard.",
        "palette": pal("#2747E6", "#FFB020", "#F5F7FB", "#FFFFFF", "#111827"),
        "presets": [
            pal("#2747E6", "#FFB020", "#F5F7FB", "#FFFFFF", "#111827", "Cobalt"),
            pal("#0F766E", "#F59E0B", "#F3F7F6", "#FFFFFF", "#0F172A", "Lagune"),
            pal("#7C3AED", "#F472B6", "#F7F5FD", "#FFFFFF", "#1F1530", "Violet"),
        ],
        "font_pair": "geometric",
        "corners": "soft",
        "sections": ALL,
        "cta_label": "Me contacter",
        "premium": False,
    },
    {
        "code": "chantier",
        "name": "Chantier",
        "category": "artisan_btp",
        "layout": "split_photo",
        "description": "Robuste et net, bleu marine et orange sécurité. Tes prestations et tes réalisations "
        "en premier, le bouton devis toujours visible.",
        "palette": pal("#1F3A5F", "#F28C28", "#F3F1EC", "#FFFFFF", "#1B1F24"),
        "presets": [
            pal("#1F3A5F", "#F28C28", "#F3F1EC", "#FFFFFF", "#1B1F24", "Marine & orange"),
            pal("#2F3B2F", "#E2B33C", "#F2F1EA", "#FFFFFF", "#1C201C", "Kaki"),
            pal("#7A2E1D", "#F2B544", "#F6F0EA", "#FFFFFF", "#231815", "Brique"),
        ],
        "font_pair": "system",
        "corners": "sharp",
        "sections": ["services", "gallery", "about", "area", "hours", "contact", "links"],
        "cta_label": "Demander un devis",
        "premium": False,
    },
    {
        "code": "eclat",
        "name": "Éclat",
        "category": "beaute",
        "layout": "centered",
        "description": "Doux et raffiné, tons rose poudré et titres en serif. Pour coiffeuses, esthéticiennes, "
        "onglerie et bien-être.",
        "palette": pal("#9C3D54", "#E8B4A0", "#FBF5F2", "#FFFFFF", "#2B1D21"),
        "presets": [
            pal("#9C3D54", "#E8B4A0", "#FBF5F2", "#FFFFFF", "#2B1D21", "Rose poudré"),
            pal("#6B4E9B", "#E6C3E9", "#F8F5FB", "#FFFFFF", "#241B30", "Lilas"),
            pal("#8A5A2B", "#E9C9A4", "#FAF6F0", "#FFFFFF", "#2A1F15", "Caramel"),
        ],
        "font_pair": "serif",
        "corners": "rounded",
        "sections": ["about", "services", "gallery", "hours", "area", "contact", "links"],
        "cta_label": "Prendre rendez-vous",
        "premium": False,
    },
    {
        "code": "saveur",
        "name": "Saveur",
        "category": "restauration",
        "layout": "magazine",
        "description": "Ambiance magazine gourmande : grande photo, terre cuite et safran. Ta carte, tes "
        "horaires et la réservation en un coup d'œil.",
        "palette": pal("#B5452A", "#E9B949", "#FBF6EE", "#FFFFFF", "#2A1A12"),
        "presets": [
            pal("#B5452A", "#E9B949", "#FBF6EE", "#FFFFFF", "#2A1A12", "Terre cuite"),
            pal("#2D6A4F", "#F4A259", "#F6F7F0", "#FFFFFF", "#1B2A22", "Basilic"),
            pal("#E9B949", "#B5452A", "#1A120D", "#241913", "#F7EFE6", "Braise"),
        ],
        "font_pair": "serif",
        "corners": "soft",
        "sections": ["about", "services", "gallery", "hours", "area", "contact", "links"],
        "cta_label": "Réserver une table",
        "premium": True,
    },
    {
        "code": "atelier",
        "name": "Atelier",
        "category": "mode",
        "layout": "editorial",
        "description": "Éditorial noir et ivoire, comme un lookbook : grands titres, lignes fines et galerie "
        "mise en valeur. Pour couturiers et créateurs.",
        "palette": pal("#111111", "#C8A97E", "#F7F4EF", "#FFFFFF", "#111111"),
        "presets": [
            pal("#111111", "#C8A97E", "#F7F4EF", "#FFFFFF", "#111111", "Ivoire"),
            pal("#7B1E3A", "#D9B26F", "#F8F3F0", "#FFFFFF", "#1E1114", "Bordeaux"),
            pal("#C8A97E", "#F7F4EF", "#111111", "#1A1A1A", "#F4F1EC", "Noir"),
        ],
        "font_pair": "serif",
        "corners": "sharp",
        "sections": ["about", "gallery", "services", "contact", "area", "hours", "links"],
        "cta_label": "Commander une pièce",
        "premium": True,
    },
    {
        "code": "code",
        "name": "Code",
        "category": "tech_freelance",
        "layout": "card",
        "description": "Mode sombre, indigo électrique et titres techniques : la carte de visite des "
        "développeurs, designers et freelances du numérique.",
        "palette": pal("#6D5DF6", "#22D3EE", "#0F1420", "#161C2C", "#E6E9F2"),
        "presets": [
            pal("#6D5DF6", "#22D3EE", "#0F1420", "#161C2C", "#E6E9F2", "Indigo nuit"),
            pal("#10B981", "#A3E635", "#0B1311", "#111C19", "#E3F1EC", "Terminal"),
            pal("#4F46E5", "#06B6D4", "#F5F6FB", "#FFFFFF", "#111827", "Clair"),
        ],
        "font_pair": "mono",
        "corners": "soft",
        "sections": ["about", "services", "links", "gallery", "contact", "hours", "area"],
        "cta_label": "Discuter de mon projet",
        "premium": False,
    },
    {
        "code": "serenite",
        "name": "Sérénité",
        "category": "sante",
        "layout": "centered",
        "description": "Calme et rassurant : bleu soin, vert apaisant, beaucoup d'air. Horaires et prise de "
        "rendez-vous mis en avant.",
        "palette": pal("#1E6F8C", "#5BB89A", "#F2F8FA", "#FFFFFF", "#14303A"),
        "presets": [
            pal("#1E6F8C", "#5BB89A", "#F2F8FA", "#FFFFFF", "#14303A", "Bleu soin"),
            pal("#2F7A5F", "#9ED2BE", "#F2F8F5", "#FFFFFF", "#15302A", "Vert d'eau"),
            pal("#3B5BA9", "#9CC3FF", "#F4F7FC", "#FFFFFF", "#18233D", "Azur"),
        ],
        "font_pair": "humanist",
        "corners": "rounded",
        "sections": ["about", "services", "hours", "area", "contact", "gallery", "links"],
        "cta_label": "Prendre rendez-vous",
        "premium": False,
    },
    {
        "code": "cabinet",
        "name": "Cabinet",
        "category": "conseil_juridique",
        "layout": "editorial",
        "description": "Sobre et institutionnel : marine profond, filet doré, titres serif. Pour avocats, "
        "notaires, comptables et consultants.",
        "palette": pal("#1C2B4A", "#B08D57", "#F6F4EF", "#FFFFFF", "#1A2233"),
        "presets": [
            pal("#1C2B4A", "#B08D57", "#F6F4EF", "#FFFFFF", "#1A2233", "Marine & or"),
            pal("#3A3A3A", "#8C6D46", "#F5F4F2", "#FFFFFF", "#1E1E1E", "Graphite"),
            pal("#1F4D3A", "#B9975B", "#F4F5F0", "#FFFFFF", "#17241E", "Vert anglais"),
        ],
        "font_pair": "serif",
        "corners": "sharp",
        "sections": ["about", "services", "contact", "area", "hours", "links", "gallery"],
        "cta_label": "Demander une consultation",
        "premium": True,
    },
    {
        "code": "boutique",
        "name": "Boutique",
        "category": "commerce",
        "layout": "cover_color",
        "description": "Vitrine colorée et accueillante : vert marché, jaune soleil. Produits, horaires et "
        "commande WhatsApp à portée de pouce.",
        "palette": pal("#12805C", "#FFC93C", "#F4F8F5", "#FFFFFF", "#13241C"),
        "presets": [
            pal("#12805C", "#FFC93C", "#F4F8F5", "#FFFFFF", "#13241C", "Marché"),
            pal("#C2410C", "#FDE68A", "#FBF6F1", "#FFFFFF", "#26170F", "Épices"),
            pal("#1D4ED8", "#FCD34D", "#F4F6FC", "#FFFFFF", "#111A33", "Bleu roi"),
        ],
        "font_pair": "rounded",
        "corners": "rounded",
        "sections": ["about", "services", "gallery", "hours", "area", "contact", "links"],
        "cta_label": "Commander sur WhatsApp",
        "premium": False,
    },
    {
        "code": "objectif",
        "name": "Objectif",
        "category": "evenementiel_photo",
        "layout": "magazine",
        "description": "Plein cadre et contrasté : ton portfolio d'abord, sur fond noir, avec un accent corail. "
        "Pour photographes, vidéastes et événementiel.",
        "palette": pal("#FD6552", "#F5F5F0", "#0E0E10", "#18181B", "#F4F4F5"),
        "presets": [
            pal("#FD6552", "#F5F5F0", "#0E0E10", "#18181B", "#F4F4F5", "Noir corail"),
            pal("#E9C46A", "#F5F5F0", "#0F1012", "#1A1B1F", "#F2F2EE", "Noir doré"),
            pal("#111111", "#FD6552", "#F6F5F2", "#FFFFFF", "#111111", "Galerie blanche"),
        ],
        "font_pair": "archivo",
        "corners": "sharp",
        "sections": ["gallery", "about", "services", "contact", "area", "hours", "links"],
        "cta_label": "Réserver une date",
        "premium": True,
    },
    {
        "code": "savoir",
        "name": "Savoir",
        "category": "education",
        "layout": "card",
        "description": "Vivant et bienveillant : violet et jaune, formes arrondies. Pour enseignants, "
        "répétiteurs, coachs et centres de formation.",
        "palette": pal("#5B3FD9", "#FFB703", "#F6F4FD", "#FFFFFF", "#1E1838"),
        "presets": [
            pal("#5B3FD9", "#FFB703", "#F6F4FD", "#FFFFFF", "#1E1838", "Violet soleil"),
            pal("#0E7490", "#FB923C", "#F2F8FA", "#FFFFFF", "#102A33", "Océan"),
            pal("#BE185D", "#FDE047", "#FCF4F8", "#FFFFFF", "#2A1020", "Framboise"),
        ],
        "font_pair": "rounded",
        "corners": "rounded",
        "sections": ["about", "services", "hours", "area", "gallery", "contact", "links"],
        "cta_label": "Réserver un cours",
        "premium": False,
    },
    {
        "code": "prestige",
        "name": "Prestige",
        "category": "universel",
        "layout": "editorial",
        "description": "Haut de gamme : fond nuit, or champagne, titres serif. Pour les métiers qui misent "
        "sur l'excellence et le sur-mesure.",
        "palette": pal("#C9A45C", "#E8DCC2", "#101418", "#171D23", "#EDE8DF"),
        "presets": [
            pal("#C9A45C", "#E8DCC2", "#101418", "#171D23", "#EDE8DF", "Nuit champagne"),
            pal("#B4865B", "#E9D8C4", "#15110E", "#1E1915", "#F1E9DF", "Cuir"),
            pal("#1C1C1C", "#C9A45C", "#F7F5F0", "#FFFFFF", "#1C1C1C", "Ivoire & or"),
        ],
        "font_pair": "serif",
        "corners": "soft",
        "sections": ALL,
        "cta_label": "Prendre contact",
        "premium": True,
    },
]


def load(apps, schema_editor):
    Theme = apps.get_model("themes", "Theme")
    for order, data in enumerate(THEMES):
        Theme.objects.update_or_create(
            code=data["code"],
            defaults={
                "name": data["name"],
                "category": data["category"],
                "description": data["description"],
                "layout": data["layout"],
                "palette": data["palette"],
                "palette_presets": data["presets"],
                "font_pair": data["font_pair"],
                "corners": data["corners"],
                "sections": data["sections"],
                "cta_label": data["cta_label"],
                "is_active": True,
                "is_premium": data["premium"],
                "order": order * 10,
            },
        )


def unload(apps, schema_editor):
    Theme = apps.get_model("themes", "Theme")
    ProfileTheme = apps.get_model("themes", "ProfileTheme")
    used = set(ProfileTheme.objects.values_list("theme__code", flat=True))
    Theme.objects.filter(code__in=[t["code"] for t in THEMES]).exclude(code__in=used).delete()


class Migration(migrations.Migration):
    dependencies = [("themes", "0001_initial")]
    operations = [migrations.RunPython(load, unload)]
