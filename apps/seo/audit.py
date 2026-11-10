"""`manage.py seo_audit --crawl`: crawl the public pages in-process (Django test Client, no network).

Checks on every crawled page (SEO audit 2026-11-10 #13):
- exactly one <h1>; <title> ≤ 60 characters; meta description of 120 to 160 characters;
- canonical == absolute URL of the page; meta robots coherent with the expected indexability;
- JSON-LD parses and every "@id" reference resolves inside its block;
- every internal link answers 200 or 301 (results cached across pages);
- the breadcrumb never links to a noindex page.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.http.request import validate_host
from django.test import Client
from django.urls import reverse

from . import jsonld, selectors

TITLE_MAX = 60
DESCRIPTION_MIN = 120
DESCRIPTION_MAX = 160
LINK_OK = {200, 301}


class PageParser(HTMLParser):
    """Collects the SEO-relevant parts of a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.links: list[str] = []
        self.breadcrumb_links: list[str] = []
        self.jsonld: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._breadcrumb_depth = 0
        self._nav_depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "h1":
            self.h1 += 1
        elif tag == "title":
            self._in_title, self._buffer = True, []
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"].lower()] = a.get("content", "")
        elif tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonical = a.get("href", "")
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld, self._buffer = True, []
        elif tag == "nav":
            self._nav_depth += 1
            if "breadcrumb" in a.get("class", "").split() and not self._breadcrumb_depth:
                self._breadcrumb_depth = self._nav_depth
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if self._breadcrumb_depth:
                self.breadcrumb_links.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = "".join(self._buffer).strip()
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._buffer))
        elif tag == "nav":
            if self._breadcrumb_depth == self._nav_depth:
                self._breadcrumb_depth = 0
            self._nav_depth -= 1

    def handle_data(self, data):
        if self._in_title or self._in_jsonld:
            self._buffer.append(data)


@dataclass
class PageReport:
    path: str
    errors: list[str] = field(default_factory=list)


@dataclass
class CrawlReport:
    pages: list[PageReport] = field(default_factory=list)

    @property
    def errors(self) -> list[tuple[str, str]]:
        return [(page.path, error) for page in self.pages for error in page.errors]


class Crawler:
    def __init__(self, client: Client | None = None):
        site = urlsplit(settings.SITE_URL)
        self.host = site.netloc
        self.secure = site.scheme == "https"
        self.client = client or Client(raise_request_exception=False)
        self._status: dict[str, int] = {}
        self._robots: dict[str, str] = {}

    # --- fetching ----------------------------------------------------------------------------

    def fetch(self, path: str):
        extra = {"HTTP_HOST": self.host} if validate_host(self.host, settings.ALLOWED_HOSTS) else {}
        response = self.client.get(path, secure=self.secure, **extra)  # canonical host when it is served
        self._status[path] = response.status_code
        if response.status_code == 200 and "html" in response.get("Content-Type", ""):
            parser = PageParser()
            parser.feed(response.content.decode(response.charset or "utf-8", "replace"))
            self._robots[path] = parser.meta.get("robots", "")
            return response, parser
        return response, None

    def status(self, path: str) -> int:
        if path not in self._status:
            self.fetch(path)
        return self._status[path]

    def robots(self, path: str) -> str:
        if path not in self._status:
            self.fetch(path)
        return self._robots.get(path, "")

    def internal_path(self, href: str, base: str) -> str | None:
        """Path (with query) of an internal link, or None for external / non-HTTP links."""
        absolute = urljoin(f"{settings.SITE_URL}{base}", href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.netloc != self.host:
            return None
        return parts.path + (f"?{parts.query}" if parts.query else "")

    # --- checks ------------------------------------------------------------------------------

    def check_page(self, path: str, *, indexable: bool) -> PageReport:
        report = PageReport(path)
        err = report.errors.append
        response, page = self.fetch(path)
        if page is None:
            err(f"HTTP {response.status_code} (200 HTML attendu)")
            return report
        if page.h1 != 1:
            err(f"{page.h1} balise(s) h1 (1 attendue)")
        title = html.unescape(page.title)
        if not title or len(title) > TITLE_MAX:
            err(f"title de {len(title)} caractères (1 à {TITLE_MAX})")
        description = html.unescape(page.meta.get("description", ""))
        if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
            err(f"description de {len(description)} caractères ({DESCRIPTION_MIN} à {DESCRIPTION_MAX})")
        expected_canonical = f"{settings.SITE_URL}{path}"
        if page.canonical != expected_canonical:
            err(f"canonical {page.canonical or '(absente)'} ≠ {expected_canonical}")
        robots = page.meta.get("robots", "")
        if ("noindex" not in robots) != indexable:
            err(f"robots « {robots} » incohérent (indexable attendu : {'oui' if indexable else 'non'})")
        if not page.jsonld:
            err("aucun JSON-LD")
        for raw in page.jsonld:
            try:
                block = json.loads(raw)
            except ValueError as exc:
                err(f"JSON-LD invalide : {exc}")
                continue
            missing = jsonld.unresolved_refs(block)
            if missing:
                err(f"JSON-LD : références @id non résolues {missing}")
        for href in dict.fromkeys(page.links):
            target = self.internal_path(href, path)
            if target is None:
                continue
            code = self.status(target)
            if code not in LINK_OK:
                err(f"lien interne {target} : HTTP {code}")
        for href in page.breadcrumb_links:
            target = self.internal_path(href, path)
            if target and "noindex" in self.robots(target):
                err(f"fil d'Ariane : lien vers une page noindex {target}")
        return report

    def crawl(self, *, limit: int = 200) -> CrawlReport:
        report = CrawlReport()
        minimum = selectors.directory_min()
        report.pages.append(self.check_page("/", indexable=True))
        for profile in selectors.indexable_profiles().order_by("-content_updated_at", "-pk")[:limit]:
            report.pages.append(self.check_page(profile.get_absolute_url(), indexable=True))
        for stat in selectors.city_stats():
            path = reverse("public:city", kwargs={"city": stat["city"].slug})
            report.pages.append(self.check_page(path, indexable=stat["count"] >= minimum))
        for combo in selectors.directory_combos():
            path = reverse(
                "public:directory", kwargs={"trade_plural": combo["trade"].plural_slug, "city": combo["city"].slug}
            )
            report.pages.append(self.check_page(path, indexable=combo["count"] >= minimum))
        return report
