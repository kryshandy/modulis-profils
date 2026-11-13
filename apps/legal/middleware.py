"""Pro space locked until the current CGU + privacy policy are accepted (apps.legal.conf.LEGAL_VERSION).

New accounts accept at sign-up (notice under the login button, recorded when the account is created).
Accounts created another way (card activation, field agent) and every account after a new version
land on /espace/conditions first. Logging out, downloading one's data and the page itself stay open.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse

from .services import needs_acceptance

EXEMPT_NAMES = (
    "dashboard:login",
    "dashboard:verify",
    "dashboard:firebase_verify",
    "dashboard:logout",
    "dashboard:data_export",
    "legal:accept",
)


class TermsAcceptanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._prefix = None
        self._exempt = None

    def _paths(self):
        if self._prefix is None:
            self._prefix = reverse("dashboard:home")
            self._exempt = frozenset(reverse(name) for name in EXEMPT_NAMES)
        return self._prefix, self._exempt

    def __call__(self, request):
        prefix, exempt = self._paths()
        path = request.path_info
        if path.startswith(prefix) and path not in exempt and needs_acceptance(getattr(request, "user", None)):
            nxt = request.get_full_path() if request.method == "GET" else prefix
            target = reverse("legal:accept") + "?" + urlencode({"next": nxt})
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = target
                return response
            return HttpResponseRedirect(target)
        return self.get_response(request)
