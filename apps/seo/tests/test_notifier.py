"""kliz integration without any network call: a fake provider is injected."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from kliz import BaseProvider, IndexNowProvider, ProviderError

from apps.seo import notifier, tasks
from apps.seo.indexing import queue_urls
from apps.seo.models import IndexingLog, IndexingQueue
from apps.seo.tests.utils import indexable_profile
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

KEY = "a1b2c3d4e5f6a7b8c9d0"


class FakeProvider(BaseProvider):
    def __init__(self, fail: bool = False, retryable: bool = False, retry_after: float | None = None):
        self.fail = fail
        self.retryable = retryable
        self.retry_after = retry_after
        self.batches: list[list[str]] = []

    def notify(self, url: str) -> bool:
        return self.notify_many([url])

    def notify_many(self, urls) -> bool:
        self.batches.append(list(urls))
        if self.fail:
            raise ProviderError(
                "boom",
                provider=self.name,
                status_code=503 if self.retryable else 400,
                retryable=self.retryable,
                retry_after=self.retry_after,
            )
        return True


def test_flush_notifies_in_one_batch_and_logs():
    queue_urls(["https://profils.test/a-b", "https://profils.test/c-d"])
    fake = FakeProvider()
    assert notifier.flush_queue(providers=[fake]) == 2
    assert len(fake.batches) == 1
    assert sorted(fake.batches[0]) == ["https://profils.test/a-b", "https://profils.test/c-d"]
    assert IndexingQueue.objects.count() == 0
    log = IndexingLog.objects.get()
    assert log.provider == "FakeProvider"
    assert log.success is True
    assert log.url_count == 2
    assert log.sample_url.startswith("https://profils.test/")


def test_failure_is_logged_without_raising():
    queue_urls(["https://profils.test/a-b"])
    notifier.flush_queue(providers=[FakeProvider(fail=True)])
    log = IndexingLog.objects.get()
    assert log.success is False
    assert log.status_code == 400
    assert "boom" in log.error
    assert IndexingQueue.objects.count() == 0


def test_empty_queue_does_nothing():
    fake = FakeProvider()
    assert notifier.flush_queue(providers=[fake]) == 0
    assert fake.batches == []


def test_url_requeued_after_cutoff_is_kept():
    queue_urls(["https://profils.test/a-b"])
    IndexingQueue.objects.update(queued_at=timezone.now() + timedelta(minutes=1))
    assert notifier.flush_queue(providers=[FakeProvider()]) == 0
    assert IndexingQueue.objects.count() == 1


@override_settings(KLIZ_ENABLED=False)
def test_disabled_drops_queue_without_logging():
    queue_urls(["https://profils.test/a-b"])
    assert tasks.flush_indexing_queue.call_local() == 1
    assert IndexingQueue.objects.count() == 0
    assert IndexingLog.objects.count() == 0


@override_settings(KLIZ_ENABLED=True, KLIZ_INDEXNOW_KEY=KEY)
def test_enabled_task_uses_default_providers(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(notifier, "default_providers", lambda **kw: [fake])
    queue_urls(["https://profils.test/a-b"])
    assert tasks.flush_indexing_queue.call_local() == 1
    assert fake.batches == [["https://profils.test/a-b"]]
    assert IndexingLog.objects.filter(success=True).count() == 1


@override_settings(KLIZ_INDEXNOW_KEY=KEY, KLIZ_GSC_SITE="", KLIZ_GSC_SERVICE_ACCOUNT_FILE="")
def test_default_providers_indexnow_only():
    providers = notifier.default_providers(include_google=True)
    assert len(providers) == 1
    assert isinstance(providers[0], IndexNowProvider)
    assert providers[0].key_location == f"https://profils.test/{KEY}.txt"


@override_settings(
    KLIZ_INDEXNOW_KEY=KEY, KLIZ_GSC_SITE="https://profils.test/", KLIZ_GSC_SERVICE_ACCOUNT_FILE="/x.json"
)
def test_google_only_for_daily_catch_up(monkeypatch):
    created = []

    class FakeGsc(FakeProvider):
        def __init__(self, **kwargs):
            super().__init__()
            created.append(kwargs)

    monkeypatch.setattr(notifier, "GoogleSearchConsoleProvider", FakeGsc)
    assert len(notifier.default_providers()) == 1
    assert len(notifier.default_providers(include_google=True)) == 2
    assert created[0]["sitemap_url"] == "https://profils.test/sitemap.xml"


@pytest.fixture
def no_sleep(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr(notifier, "_sleep", delays.append)
    return delays


def test_kliz_client_settings(monkeypatch):
    captured = {}

    class SpyKliz(notifier.Kliz):
        def __init__(self, providers, **kwargs):
            captured.update(kwargs)
            super().__init__(providers, **kwargs)

    monkeypatch.setattr(notifier, "Kliz", SpyKliz)
    notifier.notify(["https://profils.test/a-b"], [FakeProvider()])
    assert captured["max_attempts"] == 3
    assert captured["deadline"] == 120
    assert captured["on_result"] is notifier.log_result


def test_log_keeps_batch_urls():
    queue_urls([f"https://profils.test/p-{i}" for i in range(3)])
    notifier.flush_queue(providers=[FakeProvider()])
    assert sorted(IndexingLog.objects.get().urls) == [f"https://profils.test/p-{i}" for i in range(3)]


def test_retryable_failure_is_retried_then_requeued_with_retry_after(no_sleep):
    queue_urls(["https://profils.test/a-b"])
    fake = FakeProvider(fail=True, retryable=True, retry_after=600)
    before = timezone.now()
    notifier.flush_queue(providers=[fake])
    assert len(fake.batches) == 1  # Retry-After above kliz max_delay: handed back to us at once
    log = IndexingLog.objects.get()
    assert log.success is False
    row = IndexingQueue.objects.get()
    assert row.url == "https://profils.test/a-b"
    assert row.not_before >= before + timedelta(seconds=600)
    # not before its Retry-After…
    assert notifier.pop_queue() == []
    assert IndexingQueue.objects.count() == 1
    # …then sent again
    IndexingQueue.objects.update(not_before=timezone.now() - timedelta(seconds=1))
    ok = FakeProvider()
    assert notifier.flush_queue(providers=[ok]) == 1
    assert ok.batches == [["https://profils.test/a-b"]]


def test_retryable_failure_without_retry_after_uses_default_delay(no_sleep):
    queue_urls(["https://profils.test/a-b"])
    fake = FakeProvider(fail=True, retryable=True)
    notifier.flush_queue(providers=[fake])
    assert len(fake.batches) == 3  # kliz retried in the same run (max_attempts=3)
    assert len(no_sleep) == 2
    assert IndexingLog.objects.get().attempts == 3
    row = IndexingQueue.objects.get()
    assert row.not_before > timezone.now() + notifier.DEFAULT_RETRY_DELAY - timedelta(minutes=1)


def test_non_retryable_failure_is_only_logged(no_sleep):
    queue_urls(["https://profils.test/a-b"])
    fake = FakeProvider(fail=True)
    notifier.flush_queue(providers=[fake])
    assert len(fake.batches) == 1
    assert IndexingQueue.objects.count() == 0
    assert IndexingLog.objects.get().success is False


def test_requeue_keeps_newer_queued_row():
    queue_urls(["https://profils.test/a-b"])
    notifier.requeue(["https://profils.test/a-b"], not_before=timezone.now() + timedelta(hours=1))
    assert IndexingQueue.objects.get().not_before is None  # the fresh change is sent at the next flush


def _log(urls, success, *, provider="IndexNowProvider", hours_ago=1):
    log = IndexingLog.objects.create(
        provider=provider, success=success, url_count=len(urls), sample_url=urls[0], urls=urls
    )
    IndexingLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
    return log


def test_catch_up_requeues_last_day_failures_only():
    gone = "https://profils.test/page-supprimee"  # a removal (410) is retried like any URL
    _log([gone, "https://profils.test/a"], success=False, hours_ago=5)
    _log(["https://profils.test/a"], success=True, hours_ago=2)  # fixed later the same day
    _log(["https://profils.test/old"], success=False, hours_ago=30)  # outside the window
    _log(["https://profils.test/ok"], success=True, hours_ago=3)
    legacy = IndexingLog.objects.create(
        provider="IndexNowProvider", success=False, sample_url="https://profils.test/legacy"
    )  # row from before the `urls` column: its sample is retried
    assert legacy.urls == []
    google = FakeProvider()
    assert notifier.catch_up(providers=[google]) == 2
    assert set(IndexingQueue.objects.values_list("url", flat=True)) == {gone, "https://profils.test/legacy"}
    assert IndexingQueue.objects.filter(not_before__isnull=False).count() == 0
    # Google (sitemap resubmission) hears once about everything pushed during the day
    assert len(google.batches) == 1
    assert set(google.batches[0]) == {gone, "https://profils.test/a", "https://profils.test/ok", legacy.sample_url}


def test_catch_up_ignores_google_logs_and_does_nothing_without_activity():
    _log(["https://profils.test/a"], success=False, provider=notifier.GOOGLE_PROVIDER)
    google = FakeProvider()
    assert notifier.catch_up(providers=[google]) == 0
    assert IndexingQueue.objects.count() == 0
    assert google.batches == []


def test_google_retryable_failure_is_not_requeued(no_sleep):
    class GoogleSearchConsoleProvider(FakeProvider):  # same name as the kliz provider
        pass

    notifier.notify(["https://profils.test/a"], [GoogleSearchConsoleProvider(fail=True, retryable=True)])
    assert IndexingQueue.objects.count() == 0


@override_settings(KLIZ_ENABLED=True, KLIZ_GSC_SITE="", KLIZ_GSC_SERVICE_ACCOUNT_FILE="")
def test_catch_up_task_enabled_without_google():
    _log(["https://profils.test/a"], success=False)
    assert tasks.indexing_daily_catch_up.call_local() == 1
    assert IndexingQueue.objects.filter(url="https://profils.test/a").exists()


def test_queue_profile_related(settings):
    from apps.seo.indexing import queue_profile_related, related_urls

    profile = indexable_profile()
    assert related_urls(profile) == ["https://profils.test/villes/douala", "https://profils.test/plombiers/douala"]
    queue_profile_related(profile)
    assert set(IndexingQueue.objects.values_list("url", flat=True)) == set(related_urls(profile))
    assert related_urls(ProfileFactory(city=None)) == []
    assert related_urls(ProfileFactory(trade=None)) == ["https://profils.test/villes/douala"]


@override_settings(KLIZ_ENABLED=False)
def test_catch_up_task_disabled():
    indexable_profile()
    assert tasks.indexing_daily_catch_up.call_local() == 0


def test_keygen_command():
    out = StringIO()
    call_command("indexnow_keygen", stdout=out)
    key = out.getvalue().strip()
    assert len(key) == 32
    assert key.isalnum()


@override_settings(KLIZ_INDEXNOW_KEY="")
def test_verify_command_requires_key():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("indexnow_verify")


@override_settings(KLIZ_INDEXNOW_KEY=KEY)
def test_verify_command(monkeypatch):
    monkeypatch.setattr(IndexNowProvider, "verify_key", lambda self, site_url=None: self.key_location)
    out = StringIO()
    call_command("indexnow_verify", stdout=out)
    assert "vérifiée" in out.getvalue()
    assert KEY not in out.getvalue()


def test_seo_audit_command():
    indexable_profile()
    ProfileFactory(bio="court")
    out = StringIO()
    call_command("seo_audit", stdout=out)
    text = out.getvalue()
    assert "Profils (hors supprimés) : 2" in text
    assert "Profils indexables : 1" in text
    assert "La présentation est trop courte." in text
