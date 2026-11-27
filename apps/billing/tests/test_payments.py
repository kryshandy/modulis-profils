"""Tests for internal payment providers, idempotent confirmation, webhooks, and reconciliation."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing import services, tasks
from apps.billing.models import Payment, Plan, Subscription
from apps.billing.providers import PaymentError, SandboxPaymentProvider
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def _sign_webhook(payload: dict, *, signature: str | None = None) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode("utf-8")
    sig = SandboxPaymentProvider().sign(body) if signature is None else signature
    headers = {"HTTP_X_SANDBOX_SIGNATURE": sig} if sig else {}
    return body, headers


class TestInitiatePayment:
    def test_initiate_sandbox_payment_creates_pending_payment(self):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)

        payment = services.initiate_payment(profile, plan, provider="sandbox", callback_url="https://profils.test/ok")

        assert payment.status == Payment.Status.PENDING
        assert payment.provider == "sandbox"
        assert payment.amount == 12000
        assert payment.currency == "XAF"
        assert payment.reference.startswith("PAY-")
        assert payment.provider_reference == f"SBX-{payment.reference}"
        assert payment.raw_payload["mode"] == "sandbox"
        assert payment.subscription is None

    def test_initiate_free_plan_rejected(self):
        profile = ProfileFactory()
        free_plan = Plan.objects.get(code=Plan.Code.FREE)

        with pytest.raises(PaymentError):
            services.initiate_payment(profile, free_plan)

    def test_initiate_unknown_provider_rejected(self):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)

        with pytest.raises(PaymentError):
            services.initiate_payment(profile, plan, provider="unknown")

    def test_initiate_without_country_rejected(self):
        profile = ProfileFactory()
        profile.user.country = None
        profile.user.save(update_fields=["country"])
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)

        with pytest.raises(PaymentError):
            services.initiate_payment(profile, plan)


class TestPaymentWebhook:
    def test_valid_webhook_confirms_payment_and_grants_plan(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, headers = _sign_webhook(
            {
                "reference": payment.reference,
                "provider_reference": payment.provider_reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": payment.amount,
                "currency": payment.currency,
            }
        )
        response = client.post(url, data=body, content_type="application/json", **headers)

        assert response.status_code == 200
        assert response.json()["status"] == Payment.Status.SUCCEEDED

        payment.refresh_from_db()
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.subscription is not None
        assert payment.subscription.source == Subscription.Source.PAYMENT
        assert services.current_plan_code(profile) == Plan.Code.ESSENTIEL

    def test_double_webhook_is_idempotent(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.PRO)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, headers = _sign_webhook(
            {
                "reference": payment.reference,
                "provider_reference": payment.provider_reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": payment.amount,
                "currency": payment.currency,
            }
        )

        first = client.post(url, data=body, content_type="application/json", **headers)
        assert first.status_code == 200
        payment.refresh_from_db()
        first_sub = payment.subscription
        assert first_sub is not None
        first_end = first_sub.ends_at

        second = client.post(url, data=body, content_type="application/json", **headers)
        assert second.status_code == 200
        assert Subscription.objects.filter(profile=profile).count() == 1
        first_sub.refresh_from_db()
        assert first_sub.ends_at == first_end

    def test_invalid_signature_returns_403_and_does_not_grant(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, headers = _sign_webhook(
            {
                "reference": payment.reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": payment.amount,
                "currency": payment.currency,
            },
            signature="deadbeef" * 8,
        )
        response = client.post(url, data=body, content_type="application/json", **headers)

        assert response.status_code == 403
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING
        assert services.current_plan_code(profile) == Plan.Code.FREE

    def test_missing_signature_returns_403(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, _ = _sign_webhook(
            {
                "reference": payment.reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": payment.amount,
                "currency": payment.currency,
            },
            signature="",
        )
        response = client.post(url, data=body, content_type="application/json")

        assert response.status_code == 403
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING

    def test_inconsistent_amount_returns_400_and_does_not_grant(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, headers = _sign_webhook(
            {
                "reference": payment.reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": 100,
                "currency": payment.currency,
            }
        )
        response = client.post(url, data=body, content_type="application/json", **headers)

        assert response.status_code == 400
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING
        assert Subscription.objects.filter(profile=profile).count() == 0

    def test_inconsistent_currency_returns_400(self, client):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        url = reverse("billing:webhook", kwargs={"provider": "sandbox"})

        body, headers = _sign_webhook(
            {
                "reference": payment.reference,
                "status": Payment.Status.SUCCEEDED,
                "amount": payment.amount,
                "currency": "EUR",
            }
        )
        response = client.post(url, data=body, content_type="application/json", **headers)

        assert response.status_code == 400
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PENDING

    def test_unknown_provider_returns_400(self, client):
        url = reverse("billing:webhook", kwargs={"provider": "unknown"})
        response = client.post(url, data=b"{}", content_type="application/json")
        assert response.status_code == 400


class TestReconciliation:
    def test_reconcile_confirms_succeeded_and_marks_failed(self):
        p_ok = ProfileFactory()
        p_fail = ProfileFactory()
        p_wait = ProfileFactory()
        p_fresh = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)

        pay_ok = services.initiate_payment(p_ok, plan)
        pay_fail = services.initiate_payment(p_fail, plan)
        pay_wait = services.initiate_payment(p_wait, plan)
        pay_fresh = services.initiate_payment(p_fresh, plan)

        old_time = timezone.now() - timedelta(minutes=30)
        Payment.objects.filter(pk=pay_ok.pk).update(
            created_at=old_time,
            raw_payload={**pay_ok.raw_payload, "simulated_status": Payment.Status.SUCCEEDED},
        )
        Payment.objects.filter(pk=pay_fail.pk).update(
            created_at=old_time,
            raw_payload={**pay_fail.raw_payload, "simulated_status": Payment.Status.FAILED},
        )
        Payment.objects.filter(pk=pay_wait.pk).update(created_at=old_time)
        Payment.objects.filter(pk=pay_fresh.pk).update(
            raw_payload={**pay_fresh.raw_payload, "simulated_status": Payment.Status.SUCCEEDED},
        )

        stats = services.reconcile_pending_payments()

        assert stats == {"checked": 3, "confirmed": 1, "failed": 1, "still_pending": 1, "errors": 0}

        pay_ok.refresh_from_db()
        pay_fail.refresh_from_db()
        pay_wait.refresh_from_db()
        pay_fresh.refresh_from_db()

        assert pay_ok.status == Payment.Status.SUCCEEDED
        assert pay_ok.subscription is not None
        assert services.current_plan_code(p_ok) == Plan.Code.ESSENTIEL
        assert pay_fail.status == Payment.Status.FAILED
        assert pay_wait.status == Payment.Status.PENDING
        assert pay_fresh.status == Payment.Status.PENDING

    def test_daily_billing_runs_reconciliation(self, sms_outbox):
        profile = ProfileFactory()
        plan = Plan.objects.get(code=Plan.Code.ESSENTIEL)
        payment = services.initiate_payment(profile, plan)
        Payment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=30),
            raw_payload={**payment.raw_payload, "simulated_status": Payment.Status.SUCCEEDED},
        )

        result = tasks.daily_billing.call_local()

        assert result["reconciled"] == 1
        assert services.current_plan_code(profile) == Plan.Code.ESSENTIEL
