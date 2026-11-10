"""SEO health report: how many pages are indexable and what blocks the others.

`--crawl` also fetches the public pages in-process and checks them (apps/seo/audit.py); the command
then exits with a non-zero status when a page has an error (usable from `make check`).
"""

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.profiles.models import Profile
from apps.profiles.services import indexability_blockers
from apps.seo import selectors
from apps.seo.audit import Crawler
from apps.seo.models import IndexingQueue


class Command(BaseCommand):
    help = "Affiche l'état SEO : profils, profils indexables, raisons de non-indexation, pages annuaire."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl", action="store_true", help="Explore aussi les pages publiques et vérifie leurs balises."
        )
        parser.add_argument(
            "--limit", type=int, default=200, help="Nombre maximal de profils explorés avec --crawl (200)."
        )

    def handle(self, *args, **options):
        self.summary()
        if options["crawl"]:
            self.crawl(max(0, options["limit"]))

    def summary(self):
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

    def crawl(self, limit: int):
        report = Crawler().crawl(limit=limit)
        errors = report.errors
        out = self.stdout.write
        out("")
        out(f"Exploration : {len(report.pages)} page(s), {len(errors)} erreur(s)")
        for path, error in errors:
            out(f"  ✗ {path} : {error}")
        if errors:
            raise CommandError(f"Audit SEO : {len(errors)} erreur(s) sur les pages publiques.")
        out("  ✓ aucune erreur")
