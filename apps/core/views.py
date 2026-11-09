from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request):
    """Liveness + database check, used by Docker and uptime monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # pragma: no cover - only when the DB is down
        return JsonResponse({"status": "error", "db": False}, status=503)
    response = HttpResponse("ok", content_type="text/plain")
    response["X-Robots-Tag"] = "noindex"
    return response
