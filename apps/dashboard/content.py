"""Static helper content: example sentences to help pros write their presentation (no AI)."""

from django.utils.translation import gettext as _

from apps.core.models import Trade
from apps.profiles.models import Profile


def bio_suggestions(profile: Profile) -> list[str]:
    """Sentences the pro can tap to insert, adapted to the segment, trade and city."""
    job = (profile.title or _("professionnel")).lower()
    city = profile.city.name if profile.city else _("ma ville")
    district = profile.district or city
    values = {"job": job, "city": city, "district": district}
    liberal = profile.trade is not None and profile.trade.segment == Trade.Segment.LIBERAL
    if liberal:
        sentences = [
            _("Je suis %(job)s à %(city)s et j'accompagne particuliers et entreprises."),
            _("J'ai plusieurs années d'expérience et je m'adapte à chaque client."),
            _("Je propose un premier échange gratuit pour comprendre votre besoin."),
            _("Je travaille sur rendez-vous, à mon bureau ou à distance."),
            _("Je respecte les délais et je reste joignable sur WhatsApp."),
            _("Mes tarifs sont clairs et annoncés avant de commencer."),
        ]
    else:
        sentences = [
            _("Je suis %(job)s à %(city)s, quartier %(district)s."),
            _("Je fais ce métier depuis plusieurs années et mes clients me recommandent."),
            _("Je me déplace rapidement chez vous, dans tout %(city)s."),
            _("Le devis est gratuit et le prix est annoncé avant les travaux."),
            _("J'utilise du matériel de qualité et je garantis mon travail."),
            _("Je suis disponible du lundi au samedi, écrivez-moi sur WhatsApp."),
        ]
    return [s % values for s in sentences]


def service_examples(profile: Profile) -> list[str]:
    if profile.trade is not None and profile.trade.segment == Trade.Segment.LIBERAL:
        return [_("Consultation"), _("Accompagnement mensuel"), _("Formation"), _("Devis sur mesure")]
    return [_("Dépannage rapide"), _("Installation"), _("Réparation"), _("Devis gratuit")]
