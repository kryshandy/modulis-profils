"""SEO health report: how many pages are indexable and what blocks the others."""

from collections import Counter

from django.core.management.base import BaseCommand

from apps.profiles.models import Profile
from apps.profiles.services import indexability_blockers
from apps.seo import selectors
from apps.seo.models import IndexingQueue


class Command(BaseCommand):
    help = "Affiche l'état SEO : profils, profils indexables, raisons de non-indexation, pages annuaire."

    def handle(self, *args, **options):
        profiles = Profile.objects.exclude(status=Profile.Status.DELETED).prefetch_related("services", "media", "links")
        total = 0
        stored_indexable = 0
        blockers: Counter[str] = Counter()
        for profile in profiles.iterator(chunk_size=500):
            total += 1
            stored_indexable += profile.is_indexable
            for reason in indexability_blockers(profile):
                blockers[str(reason)] += 1
        minimum = selectors.directory_min()
        out = self.stdout.write
        out(f"Profils (hors supprimés) : {total}")
        out(f"Profils indexables : {stored_indexable}")
        out(f"Pages villes publiées (≥ {minimum} profils) : {len(selectors.city_stats(minimum))}")
        out(f"Pages annuaire métier×ville publiées (≥ {minimum} profils) : {len(selectors.directory_combos(minimum))}")
        out(f"URL en attente de notification : {IndexingQueue.objects.count()}")
        out("Raisons de non-indexation :")
        if not blockers:
            out("  (aucune)")
        for reason, count in blockers.most_common():
            out(f"  {count:>6}  {reason}")
