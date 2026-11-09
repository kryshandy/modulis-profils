from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL,
        "TURNSTILE_SITE_KEY": settings.TURNSTILE_SITE_KEY,
    }
