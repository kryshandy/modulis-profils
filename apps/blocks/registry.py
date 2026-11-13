"""The block library: what a pro can add to a page, field by field (ADR-0012).

Everything a block may contain is declared here: plain-text fields with a maximum length, a fixed
list of choices, https links, video links from two known providers, a bounded number of repeated
items and of images. Nothing else is accepted (no HTML, no CSS, no script, no embed code), so a page
built with blocks keeps the platform guarantees: server rendering, one h1, h2 per block and h3 per
item, escaped text, light images, strict CSP, and the same automatic SEO as the templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

MAX_BLOCKS = 12  # per page
MAX_BLOCK_IMAGES = 30  # per page, all blocks together
TITLE_MAX = 90


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"  # text | textarea | url | video | choice
    max_length: int = 120
    required: bool = False
    choices: tuple[tuple[str, str], ...] = ()
    help: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class Items:
    label: str
    max_items: int
    fields: tuple[Field, ...]
    images: tuple[tuple[str, str], ...] = ()  # per-item image slots: (slot, label)
    min_items: int = 1


@dataclass(frozen=True)
class BlockType:
    kind: str
    label: str
    description: str
    fields: tuple[Field, ...] = ()
    items: Items | None = None
    images: tuple[tuple[str, str], ...] = ()  # block image slots: (slot, label)
    image_required: bool = False
    alignable: bool = False
    icon: str = "text"
    example: dict = field(default_factory=dict)


TITLE = Field("title", _("Titre du bloc"), max_length=TITLE_MAX, help=_("Devient un sous-titre (h2) de ta page."))

BUTTON_ACTIONS = (
    ("whatsapp", _("Écrire sur WhatsApp")),
    ("call", _("Appeler")),
    ("link", _("Ouvrir un lien")),
    ("none", _("Pas de bouton")),
)
IMAGE_SIDES = (("right", _("Image à droite")), ("left", _("Image à gauche")))

BLOCK_TYPES: dict[str, BlockType] = {
    t.kind: t
    for t in (
        BlockType(
            "text",
            _("Texte"),
            _("Un paragraphe libre : ton histoire, ta méthode, tes garanties."),
            fields=(TITLE, Field("body", _("Texte"), "textarea", 3000, required=True)),
            alignable=True,
            icon="text",
            example={"title": "Notre méthode", "body": "Chaque chantier commence par une visite gratuite…"},
        ),
        BlockType(
            "text_image",
            _("Texte + image"),
            _("Un texte à côté d'une photo, pour mettre une réalisation ou ton atelier en avant."),
            fields=(
                TITLE,
                Field("body", _("Texte"), "textarea", 1500, required=True),
                Field("side", _("Position de l'image"), "choice", choices=IMAGE_SIDES),
            ),
            images=(("image", _("Image")),),
            image_required=True,
            icon="image",
        ),
        BlockType(
            "banner",
            _("Bannière d'appel"),
            _("Un bandeau qui attire l'œil avec un bouton : promotion, devis gratuit, réservation."),
            fields=(
                Field("title", _("Accroche"), max_length=TITLE_MAX, required=True),
                Field("text", _("Texte"), "textarea", 300),
                Field("button_action", _("Bouton"), "choice", choices=BUTTON_ACTIONS),
                Field("button_label", _("Texte du bouton"), max_length=40, placeholder=_("Demander un devis")),
                Field("button_url", _("Lien du bouton (https://…)"), "url", 300),
            ),
            alignable=True,
            icon="sparkle",
        ),
        BlockType(
            "faq",
            _("Questions fréquentes"),
            _("Les questions que tes clients posent toujours. Google les comprend (données structurées FAQ)."),
            fields=(TITLE,),
            items=Items(
                _("Question"),
                12,
                (
                    Field("q", _("Question"), max_length=160, required=True),
                    Field("a", _("Réponse"), "textarea", 800, required=True),
                ),
            ),
            icon="help",
        ),
        BlockType(
            "testimonials",
            _("Avis clients"),
            _("Ce que disent tes clients, avec leur accord. Pas d'avis inventé : c'est interdit."),
            fields=(TITLE,),
            items=Items(
                _("Avis"),
                8,
                (
                    Field("quote", _("Avis"), "textarea", 400, required=True),
                    Field("author", _("Prénom et initiale"), max_length=60, required=True, placeholder="Awa N."),
                    Field("role", _("Précision"), max_length=80, placeholder=_("Cliente à Bonamoussadi")),
                ),
            ),
            icon="user",
        ),
        BlockType(
            "before_after",
            _("Avant / après"),
            _("Montre la transformation : chantier, coiffure, rénovation, retouche."),
            fields=(TITLE, Field("intro", _("Introduction"), "textarea", 300)),
            items=Items(
                _("Paire de photos"),
                4,
                (Field("caption", _("Légende"), max_length=120),),
                images=(("before", _("Avant")), ("after", _("Après"))),
            ),
            icon="camera",
        ),
        BlockType(
            "steps",
            _("Étapes"),
            _("Comment ça se passe, étape par étape : de la prise de contact à la livraison."),
            fields=(TITLE,),
            items=Items(
                _("Étape"),
                6,
                (
                    Field("title", _("Étape"), max_length=80, required=True),
                    Field("text", _("Détail"), "textarea", 300),
                ),
            ),
            icon="list",
        ),
        BlockType(
            "figures",
            _("Chiffres clés"),
            _("Tes chiffres qui rassurent : années d'expérience, clients, délais."),
            fields=(TITLE,),
            items=Items(
                _("Chiffre"),
                4,
                (
                    Field("value", _("Chiffre"), max_length=12, required=True, placeholder="12 ans"),
                    Field("label", _("Signification"), max_length=60, required=True),
                ),
            ),
            alignable=True,
            icon="chart",
        ),
        BlockType(
            "video",
            _("Vidéo"),
            _("Une vidéo YouTube ou Vimeo. Elle ne se charge qu'au clic : ta page reste rapide."),
            fields=(
                TITLE,
                Field("url", _("Lien de la vidéo"), "video", 300, required=True, placeholder="https://youtu.be/…"),
                Field("caption", _("Description"), "textarea", 300),
            ),
            icon="eye",
        ),
    )
}

BACKGROUNDS = (
    ("auto", _("Selon le modèle")),
    ("surface", _("Clair")),
    ("primary", _("Couleur principale")),
    ("accent", _("Couleur d'accent")),
    ("ink", _("Sombre")),
)
SPACINGS = (("compact", _("Serré")), ("normal", _("Normal")), ("airy", _("Aéré")))
ALIGNS = (("start", _("À gauche")), ("center", _("Centré")))
STYLE_DEFAULTS = {"background": "auto", "spacing": "normal", "align": "start"}
STYLE_CHOICES = {"background": BACKGROUNDS, "spacing": SPACINGS, "align": ALIGNS}


def get_type(kind: str) -> BlockType | None:
    return BLOCK_TYPES.get(kind)


def image_slots(block_type: BlockType, item_count: int) -> list[str]:
    """Every image slot a block of this type may hold (per-item slots are suffixed with the index)."""
    slots = [slot for slot, _label in block_type.images]
    if block_type.items:
        for i in range(min(item_count, block_type.items.max_items)):
            slots += [f"{slot}_{i}" for slot, _label in block_type.items.images]
    return slots
