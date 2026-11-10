"""Page content services (the only writers of profile content), images, slugs and duplicate bios."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.dashboard.tests.helpers import make_image
from apps.moderation.models import Report
from apps.moderation.services import DUPLICATE_BIO_MARKER
from apps.profiles import images
from apps.profiles import services as s
from apps.profiles.models import Profile, ProfileLink, ProfileMedia, ProfileService, SlugRegistry
from tests.factories import COMPLETE_BIO, ProfileFactory, make_complete_profile

pytestmark = pytest.mark.django_db


# --- update_profile & co ---------------------------------------------------------------------


class TestUpdateProfile:
    def test_writes_whitelisted_fields_and_refreshes_seo(self, profile):
        s.update_profile(profile, bio=COMPLETE_BIO, district="Akwa")
        profile.refresh_from_db()
        assert profile.bio == COMPLETE_BIO and profile.district == "Akwa"
        assert profile.completeness_score == 55 and profile.content_updated_at is not None

    def test_refuses_non_editable_fields(self, profile):
        with pytest.raises(ValueError):
            s.update_profile(profile, status=Profile.Status.ACTIVE)
        with pytest.raises(ValueError):
            s.update_profile(profile, slug="hack-slug")

    def test_validates_choices(self, profile):
        with pytest.raises(ValidationError):
            s.update_profile(profile, language="de")
        with pytest.raises(ValidationError):
            s.update_profile(profile, visibility="everyone")

    def test_presentation_only_change_keeps_content_date(self, profile):
        s.update_profile(profile, cover_color="#2747E6")
        profile.refresh_from_db()
        assert profile.content_updated_at is None

    def test_language_change_is_a_content_change(self, profile, django_capture_on_commit_callbacks):
        complete = make_complete_profile()
        before = complete.content_updated_at
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            s.set_language(complete, "en")
        complete.refresh_from_db()
        assert complete.language == "en" and complete.content_updated_at > before
        assert callbacks  # indexing re-notified

    def test_local_seo_fields(self, profile):
        hours = {"sa": [["09:00", "13:00"]], "mo": [["08:00", "18:00"]], "su": []}
        s.update_profile(
            profile, latitude="4.0483", longitude=9.7043, opening_hours=hours, price_range="  5 000–50 000   FCFA "
        )
        profile.refresh_from_db()
        assert profile.latitude == Decimal("4.048300") and profile.longitude == Decimal("9.704300")
        assert profile.opening_hours == {"mo": [["08:00", "18:00"]], "sa": [["09:00", "13:00"]]}
        assert list(profile.opening_hours) == ["mo", "sa"]  # week order, closed days dropped
        assert profile.price_range == "5 000–50 000 FCFA"

    @pytest.mark.parametrize(
        "hours",
        [
            {"xx": [["08:00", "18:00"]]},
            {"mo": [["18:00", "08:00"]]},
            {"mo": [["8h", "18h"]]},
            {"mo": [["08:00"]]},
            {"mo": "08:00-18:00"},
            ["mo"],
        ],
    )
    def test_bad_opening_hours(self, profile, hours):
        with pytest.raises(ValidationError):
            s.update_profile(profile, opening_hours=hours)

    @pytest.mark.parametrize("field,value", [("latitude", "91"), ("longitude", "-181"), ("latitude", "abc")])
    def test_bad_coordinates(self, profile, field, value):
        with pytest.raises(ValidationError):
            s.update_profile(profile, **{field: value})

    def test_marks(self, profile):
        s.mark_onboarding_completed(profile)
        s.mark_tour_completed(profile)
        profile.refresh_from_db()
        first = profile.onboarding_completed_at
        assert first and profile.tour_completed_at
        s.mark_onboarding_completed(profile)
        profile.refresh_from_db()
        assert profile.onboarding_completed_at == first  # idempotent


# --- Children --------------------------------------------------------------------------------


class TestChildren:
    def test_services_crud_and_ownership(self, profile):
        a = s.add_service(profile, "Fuite", price_label="dès 5 000 FCFA")
        s.add_service(profile, "Chauffe-eau")
        s.update_service(profile, a.pk, title="Réparation de fuite", description="24 h")
        a.refresh_from_db()
        assert a.title == "Réparation de fuite" and a.description == "24 h"
        other = ProfileFactory()
        with pytest.raises(ProfileService.DoesNotExist):
            s.update_service(other, a.pk, title="Volé")
        with pytest.raises(ProfileService.DoesNotExist):
            s.delete_service(other, a.pk)
        s.delete_service(profile, a.pk)
        assert profile.services.count() == 1
        with pytest.raises(ValidationError):
            s.add_service(profile, "   ")

    def test_max_counts(self, profile):
        for i in range(s.MAX_SERVICES):
            ProfileService.objects.create(profile=profile, title=f"S{i}", order=i)
        with pytest.raises(ValidationError):
            s.add_service(profile, "Une de trop")
        for i in range(s.MAX_LINKS):
            ProfileLink.objects.create(profile=profile, kind="website", url=f"https://a.test/{i}", order=i)
        with pytest.raises(ValidationError):
            s.add_link(profile, "website", "https://b.test")
        for i in range(s.MAX_MEDIA):
            ProfileMedia.objects.create(profile=profile, image=f"x{i}.webp", order=i)
        with pytest.raises(ValidationError):
            s.add_media(profile, make_image())

    def test_links_only_https_and_known_kinds(self, profile):
        for kind, url in [("website", "http://a.test"), ("website", "javascript:alert(1)"), ("myspace", "https://a")]:
            with pytest.raises(ValidationError):
                s.add_link(profile, kind, url)
        link = s.add_link(profile, "facebook", "https://facebook.com/x")
        s.update_link(profile, link.pk, kind="instagram", url="https://instagram.com/x")
        link.refresh_from_db()
        assert link.kind == "instagram"
        with pytest.raises(ProfileLink.DoesNotExist):
            s.delete_link(ProfileFactory(), link.pk)
        s.delete_link(profile, link.pk)
        assert not profile.links.exists()

    def test_move_item(self, profile):
        a = s.add_service(profile, "A")
        b = s.add_service(profile, "B")
        c = s.add_service(profile, "C")
        s.move_item(profile, "service", c.pk, "up")
        assert list(profile.services.values_list("pk", flat=True)) == [a.pk, c.pk, b.pk]
        s.move_item(profile, "service", a.pk, "up")  # already first: no-op
        s.move_item(profile, "service", a.pk, "down")
        assert list(profile.services.values_list("pk", flat=True)) == [c.pk, a.pk, b.pk]
        with pytest.raises(ProfileService.DoesNotExist):
            s.move_item(ProfileFactory(), "service", a.pk, "up")
        with pytest.raises(ValueError):
            s.move_item(profile, "card", a.pk, "up")

    def test_media_caption_and_delete_removes_files_after_commit(self, profile, django_capture_on_commit_callbacks):
        media = s.add_media(profile, make_image(size=(1600, 1200)))
        names = images.stored_file_names(media.image.name)
        assert all(default_storage.exists(n) for n in names)  # main + 160 + 400 + 800
        s.update_media(profile, media.pk, caption="  Avant / après  ")
        media.refresh_from_db()
        assert media.caption == "Avant / après"
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            s.delete_media(profile, media.pk)
        assert default_storage.exists(names[0])  # not before the commit
        for callback in callbacks:
            callback()
        assert not any(default_storage.exists(n) for n in names)


# --- Images ----------------------------------------------------------------------------------


def _size(name):
    with default_storage.open(name) as handle, Image.open(handle) as img:
        return img.format, img.size


class TestImages:
    def test_photo_main_and_variants(self, profile):
        s.set_photo(profile, make_image(size=(1600, 1200)))
        profile.refresh_from_db()
        assert (profile.photo_width, profile.photo_height) == (800, 600)
        base = profile.photo.name[: -len(".webp")]
        assert _size(profile.photo.name) == ("WEBP", (800, 600))
        assert _size(f"{base}-160.webp") == ("WEBP", (160, 120))
        assert _size(f"{base}-400.webp") == ("WEBP", (400, 300))
        assert not default_storage.exists(f"{base}-800.webp")  # the photo is never wider than 800
        assert s.image_variants(profile.photo) == [
            (default_storage.url(f"{base}-160.webp"), 160),
            (default_storage.url(f"{base}-400.webp"), 400),
            (profile.photo.url, 800),
        ]

    def test_gallery_variants_include_800(self, profile):
        media = s.add_media(profile, make_image(size=(2400, 1200)))
        assert (media.width, media.height) == (1200, 600)
        widths = [w for _url, w in s.image_variants(media.image)]
        assert widths == [160, 400, 800, 1200]
        base = media.image.name[: -len(".webp")]
        assert _size(f"{base}-800.webp") == ("WEBP", (800, 400))

    def test_small_image_has_only_smaller_variants(self, profile):
        media = s.add_media(profile, make_image(size=(300, 200)))
        assert [w for _url, w in s.image_variants(media.image)] == [160, 300]

    def test_legacy_file_without_width(self, profile):
        media = ProfileMedia.objects.create(profile=profile, image="profiles/x/gallery/old.webp")
        assert s.image_variants(media.image) == [(media.image.url, 0)]
        assert s.image_variants(ProfileFactory().photo) == []

    def test_replacing_photo_deletes_old_files_and_variants(self, profile, django_capture_on_commit_callbacks):
        s.set_photo(profile, make_image())
        old = images.stored_file_names(profile.photo.name)
        with django_capture_on_commit_callbacks(execute=True):
            s.set_photo(profile, make_image())
        assert not any(default_storage.exists(n) for n in old)
        with django_capture_on_commit_callbacks(execute=True):
            current = images.stored_file_names(profile.photo.name)
            s.remove_photo(profile)
        profile.refresh_from_db()
        assert not profile.photo and profile.photo_width == 0
        assert not any(default_storage.exists(n) for n in current)

    @pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
    def test_only_jpeg_png_webp_are_decoded(self, fmt):
        buf = io.BytesIO()
        Image.new("RGB", (40, 40)).save(buf, format=fmt)
        with pytest.raises(ValidationError, match="pas une photo"):
            images.process_image(SimpleUploadedFile(f"a.{fmt.lower()}", buf.getvalue()))

    def test_webp_source_accepted(self):
        buf = io.BytesIO()
        Image.new("RGB", (40, 40)).save(buf, format="WEBP")
        content = images.process_image(SimpleUploadedFile("a.webp", buf.getvalue()))
        assert content.image_size == (40, 40) and content.variants == []

    def test_delete_profile_removes_variants(self, profile, django_capture_on_commit_callbacks):
        s.set_photo(profile, make_image())
        media = s.add_media(profile, make_image())
        names = images.stored_file_names(profile.photo.name) + images.stored_file_names(media.image.name)
        with django_capture_on_commit_callbacks(execute=True):
            s.delete_profile(profile)
        assert not any(default_storage.exists(n) for n in names)


# --- Slugs -----------------------------------------------------------------------------------


class TestSlugHistory:
    def test_retired_at_is_set_and_counted(self, settings):
        profile = ProfileFactory(slug="premier-nom-pro")
        s.change_slug(profile, "deuxieme-nom-pro")
        old = SlugRegistry.objects.get(slug="premier-nom-pro")
        assert old.kind == SlugRegistry.Kind.OLD and old.retired_at is not None
        assert s.slug_changes_last_year(profile) == 1

    def test_quota_uses_retirement_date_not_creation_date(self, settings):
        """A slug created 2 years ago but retired today counts in this year's quota."""
        settings.SLUG_MAX_CHANGES_PER_YEAR = 1
        profile = ProfileFactory(slug="tres-ancien-nom")
        SlugRegistry.objects.filter(slug="tres-ancien-nom").update(created_at=timezone.now() - timedelta(days=730))
        s.change_slug(profile, "nouveau-nom-pro")
        with pytest.raises(ValidationError, match="3 fois"):
            s.change_slug(profile, "encore-un-nom")

    def test_old_retirements_do_not_count(self):
        profile = ProfileFactory(slug="nom-numero-un")
        s.change_slug(profile, "nom-numero-deux")
        SlugRegistry.objects.filter(slug="nom-numero-un").update(retired_at=timezone.now() - timedelta(days=400))
        assert s.slug_changes_last_year(profile) == 0

    def test_back_to_own_old_slug_swaps_kinds(self):
        profile = ProfileFactory(slug="mon-premier-nom")
        s.change_slug(profile, "mon-second-nom")
        s.change_slug(profile, "mon-premier-nom")
        profile.refresh_from_db()
        assert profile.slug == "mon-premier-nom"
        first = SlugRegistry.objects.get(slug="mon-premier-nom")
        second = SlugRegistry.objects.get(slug="mon-second-nom")
        assert first.kind == SlugRegistry.Kind.CURRENT and first.retired_at is None and first.profile == profile
        assert second.kind == SlugRegistry.Kind.OLD and second.retired_at is not None
        assert s.resolve_slug("mon-second-nom") == (SlugRegistry.Kind.OLD, profile)

    def test_someone_elses_old_slug_stays_forbidden(self):
        owner = ProfileFactory(slug="nom-du-premier")
        s.change_slug(owner, "nom-du-premier-bis")
        other = ProfileFactory()
        with pytest.raises(ValidationError, match="déjà prise"):
            s.change_slug(other, "nom-du-premier")


# --- Duplicate bios → moderation -------------------------------------------------------------


class TestDuplicateBioReport:
    def test_copy_is_reported_once(self, complete_profile):
        copy = ProfileFactory(trade=complete_profile.trade, city=complete_profile.city)
        s.update_profile(copy, bio=complete_profile.bio)
        s.update_profile(copy, bio=complete_profile.bio + " Merci.")
        reports = Report.objects.filter(profile=copy)
        assert reports.count() == 1
        report = reports.get()
        assert report.reason == Report.Reason.SPAM and report.status == Report.Status.OPEN
        assert report.message.startswith(DUPLICATE_BIO_MARKER) and f"/{complete_profile.slug}" in report.message
        assert not Report.objects.filter(profile=complete_profile).exists()  # the original is never reported

    def test_new_report_after_the_first_is_closed(self, complete_profile):
        from apps.moderation.services import close_report

        copy = ProfileFactory(trade=complete_profile.trade, city=complete_profile.city)
        s.update_profile(copy, bio=complete_profile.bio)
        close_report(Report.objects.get(profile=copy), Report.Status.DISMISSED)
        s.refresh_seo_state(copy)
        assert Report.objects.filter(profile=copy, status=Report.Status.OPEN).count() == 1

    def test_unique_bio_not_reported(self, complete_profile):
        assert not Report.objects.exists()
