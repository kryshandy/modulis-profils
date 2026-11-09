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
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.batches: list[list[str]] = []

    def notify(self, url: str) -> bool:
        return self.notify_many([url])

    def notify_many(self, urls) -> bool:
        self.batches.append(list(urls))
        if self.fail:
            raise ProviderError("boom", provider=self.name, status_code=400)
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


def test_catch_up_renotifies_recent_indexable_pages():
    good = indexable_profile()
    ProfileFactory()  # not indexable
    fake = FakeProvider()
    assert notifier.catch_up(providers=[fake]) == 1
    assert fake.batches == [[f"https://profils.test/{good.slug}"]]


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
