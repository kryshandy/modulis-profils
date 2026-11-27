"""Billing webhook endpoints.

With ATOMIC_REQUESTS=True, business exceptions (PaymentError / InvalidSignatureError) are caught
and turned into HTTP error responses so no unhandled exception escapes the view.
"""

from __future__ import annotations

import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services
from .providers import InvalidSignatureError, PaymentError, get_provider

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def payment_webhook(request, provider: str) -> JsonResponse:
    """Receive and process signed payment provider webhooks."""
    try:
        provider_impl = get_provider(provider)
        data = provider_impl.parse_webhook(request)
        payment = services.confirm_payment(
            reference=data["reference"],
            provider_reference=data.get("provider_reference", ""),
            payload=data,
        )
    except InvalidSignatureError as exc:
        logger.warning("Invalid payment webhook signature for provider=%s", provider)
        return JsonResponse({"error": str(exc)}, status=403)
    except PaymentError as exc:
        logger.warning("Rejected payment webhook for provider=%s: %s", provider, exc)
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({"status": payment.status, "reference": payment.reference}, status=200)
