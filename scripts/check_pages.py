# Tour of every page (public, pro space, admin with 2FA) against the Docker database: reports 5xx errors and exceptions.
# Usage: make pages   (= docker compose exec -T web python manage.py shell < scripts/check_pages.py)
# The demo pro temporarily gets the current CGU version (restored at the end) so its pro space is covered.
import contextlib
import re

from django.contrib import admin
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.profiles.models import Profile

HOST = "localhost"
results = []


def hit(client, url, label, method="get", **kw):
    try:
        r = getattr(client, method)(url, HTTP_HOST=HOST, **kw)
        code = r.status_code
        note = ""
        if code >= 500:
            note = "SERVER ERROR"
        results.append((label, url, code, note, r))
        return r
    except Exception as exc:
        results.append((label, url, "EXC", f"{type(exc).__name__}: {exc}"[:300], None))
        return None


def links(r):
    if r is None or "text/html" not in r.get("Content-Type", ""):
        return []
    html = r.content.decode("utf-8", "ignore")
    out = []
    for href in re.findall(r'href="([^"#]+)', html):
        if (
            href.startswith("/")
            and not href.startswith("//")
            and not href.startswith("/static/")
            and not href.startswith("/media/")
        ):
            out.append(href)
    return out


# --- Public crawl (anonymous), following internal links -------------------------------------
anon = Client(raise_request_exception=False)
seen = set()
queue = [
    "/",
    "/cgu",
    "/confidentialite",
    "/mentions-legales",
    "/robots.txt",
    "/sitemap.xml",
    "/espace/connexion",
    "/introuvable-xyz",
]
for p in Profile.objects.exclude(status="deleted")[:200]:
    queue.append("/" + p.slug)
while queue and len(seen) < 400:
    url = queue.pop(0)
    if url in seen or (url.startswith("/espace/") and url != "/espace/connexion") or url.startswith("/gestion"):
        continue
    seen.add(url)
    r = hit(anon, url, "public")
    for link in links(r):
        if link not in seen:
            queue.append(link.split("?")[0] if "/espace/" not in link else link)

# --- Pro space (logged-in demo pro) --------------------------------------------------------------
pro_profile = Profile.objects.filter(status="active").order_by("id").first()
from apps.legal.conf import LEGAL_VERSION  # noqa: E402

_old = (pro_profile.user.terms_version, pro_profile.user.terms_accepted_at)
User.objects.filter(pk=pro_profile.user.pk).update(terms_version=LEGAL_VERSION)
pro = Client(raise_request_exception=False)
pro.force_login(pro_profile.user)
pro_urls = [
    "/espace/",
    "/espace/conditions",
    "/espace/parametres",
    "/espace/parametres/mes-donnees",
    "/espace/partager",
    "/espace/partager/affiche",
    "/espace/cartes",
    "/espace/statistiques",
    "/espace/aide",
    "/espace/modeles/",
]
for sec in [
    "identite",
    "contact",
    "presentation",
    "prestations",
    "galerie",
    "liens",
    "horaires",
    "apparence",
]:
    pro_urls.append(f"/espace/page/{sec}")
for step in ["nom", "metier", "photo", "contact", "fin"]:
    pro_urls.append(f"/espace/bienvenue/{step}")
pseen = set()
pq = list(pro_urls)
while pq and len(pseen) < 200:
    url = pq.pop(0)
    if url in pseen:
        continue
    pseen.add(url)
    r = hit(pro, url, "pro")
    for link in links(r):
        if link.startswith("/espace/") and "deconnexion" not in link and "supprimer" not in link and link not in pseen:
            pq.append(link)

User.objects.filter(pk=pro_profile.user.pk).update(terms_version=_old[0], terms_accepted_at=_old[1])
redirects = [(u, r["Location"]) for (lab, u, c, n, r) in results if lab == "pro" and c == 302]
print("PRO 302:", redirects)

# --- Admin (superuser with verified 2FA) ---------------------------------------------------------
su = User.objects.filter(is_superuser=True, is_active=True).order_by("id").first()
device = TOTPDevice.objects.filter(user=su, confirmed=True).first()
adm = Client(raise_request_exception=False)
adm.force_login(su)
if device:
    s = adm.session
    s[DEVICE_ID_SESSION_KEY] = device.persistent_id
    s.save()
from django.conf import settings  # noqa: E402

base = "/" + settings.ADMIN_URL
hit(adm, base, "admin")
for model, model_admin in admin.site._registry.items():
    meta = model._meta
    try:
        cl = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
    except NoReverseMatch:
        continue
    hit(adm, cl, "admin")
    hit(adm, cl + "?q=a", "admin-search")
    fake = type("R", (), {"user": su, "method": "GET", "GET": {}, "path": cl})()
    try:
        can_add = model_admin.has_add_permission(fake)
    except Exception:  # a ModelAdmin that needs a real request: test the page anyway
        can_add = True
    if can_add:  # read-only models (journal, codes, stats…) have no "add" page on purpose
        with contextlib.suppress(NoReverseMatch):
            hit(adm, reverse(f"admin:{meta.app_label}_{meta.model_name}_add"), "admin")
    obj = model._default_manager.order_by("-pk").first()
    if obj is not None:
        try:
            hit(adm, reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk]), "admin")
            hit(adm, reverse(f"admin:{meta.app_label}_{meta.model_name}_history", args=[obj.pk]), "admin")
        except NoReverseMatch:
            pass
r = hit(adm, base, "admin")
for link in set(links(r)):
    if link.startswith(base) and "logout" not in link and "delete" not in link:
        hit(adm, link, "admin-link")

bad = [x for x in results if x[2] == "EXC" or (isinstance(x[2], int) and x[2] >= 500)]
odd = [x for x in results if isinstance(x[2], int) and x[2] in (400, 403, 404, 405) and x[0] != "public"]
n_public = sum(1 for x in results if x[0] == "public")
n_pro = sum(1 for x in results if x[0] == "pro")
n_admin = sum(1 for x in results if x[0].startswith("admin"))
print(f"TOTAL {len(results)} requêtes · public {n_public} · pro {n_pro} · admin {n_admin}")
print(f"2FA device: {bool(device)} superuser: {su.phone}")
codes = {}
for x in results:
    codes[x[2]] = codes.get(x[2], 0) + 1
print("codes:", codes)
print("== ERREURS ==")
for label, url, code, note, r in bad:
    detail = note
    if r is not None and code >= 500:
        body = r.content.decode("utf-8", "ignore")
        m = re.search(r"<title>(.*?)</title>", body, re.S)
        ev = re.search(r'exception_value">(.*?)</pre>', body, re.S)
        detail = (m.group(1).strip() if m else "") + " | " + (ev.group(1).strip()[:200] if ev else "")
    print(label, url, code, detail)
print("== 4xx côté pro/admin ==")
for label, url, code, _note, _r in odd:
    print(label, url, code)
print("== 404 publics ==")
for label, url, code, _note, _r in results:
    if label == "public" and code == 404 and url != "/introuvable-xyz":
        print(url)
