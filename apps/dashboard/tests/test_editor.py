import json

import pytest
from django.urls import reverse

from apps.dashboard.services import MAX_SERVICES
from apps.profiles.models import ProfileLink, ProfileMedia, ProfileService
from tests.factories import COMPLETE_BIO

from .helpers import make_image

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def edit(section):
    return reverse("dashboard:edit", kwargs={"section": section})


@pytest.mark.parametrize(
    "section", ["identite", "metier", "contact", "presentation", "prestations", "galerie", "liens", "apparence"]
)
def test_every_section_renders(logged_client, section):
    response = logged_client.get(edit(section))
    assert response.status_code == 200
    assert 'id="panel"' in response.content.decode()


def test_unknown_section_404(logged_client):
    assert logged_client.get(edit("inconnue")).status_code == 404


def test_identity_save_without_js_redirects(logged_client, profile):
    response = logged_client.post(edit("identite"), {"display_name": "Paul Mbarga", "kind": "business"})
    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.display_name == "Paul Mbarga"
    assert profile.kind == "business"


def test_identity_save_with_htmx_returns_panel_and_toast(logged_client, profile):
    response = logged_client.post(edit("identite"), {"display_name": "Paul Mbarga", "kind": "person"}, **HX)
    assert response.status_code == 200
    assert 'id="panel"' in response.content.decode()
    assert "<html" not in response.content.decode()
    assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "success"


def test_invalid_form_htmx_shows_errors(logged_client):
    response = logged_client.post(edit("identite"), {"display_name": "", "kind": "person"}, **HX)
    assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "error"
    assert "form-field__error" in response.content.decode()


def test_presentation_save_refreshes_seo_state(logged_client, profile):
    logged_client.post(edit("presentation"), {"bio": COMPLETE_BIO})
    profile.refresh_from_db()
    assert profile.bio == COMPLETE_BIO
    assert profile.completeness_score == 55  # trade+city 20, contact 15, bio 20
    assert profile.content_updated_at is not None


def test_contact_requires_one_number(logged_client):
    response = logged_client.post(edit("contact"), {"whatsapp": "", "phone_public": ""})
    assert response.status_code == 200
    assert "au moins un numéro" in response.content.decode()


def test_contact_maps_url_must_be_https(logged_client):
    response = logged_client.post(edit("contact"), {"whatsapp": "690000001", "maps_url": "http://maps.example.com"})
    assert "https://" in response.content.decode()


def test_appearance_only_preset_colors(logged_client, profile):
    logged_client.post(edit("apparence"), {"cover_color": "#2747E6", "visibility": "private"})
    profile.refresh_from_db()
    assert profile.cover_color == "#2747E6"
    assert profile.visibility == "private"
    response = logged_client.post(edit("apparence"), {"cover_color": "#FF00FF", "visibility": "public"})
    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.cover_color == "#2747E6"


def test_metier_section(logged_client, profile):
    response = logged_client.post(
        edit("metier"), {"trade_choice": str(profile.trade_id), "city": profile.city_id, "service_area": "Tout Douala"}
    )
    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.service_area == "Tout Douala"


def test_photo_upload_in_editor(logged_client, profile):
    response = logged_client.post(edit("identite"), {"action": "photo", "photo": make_image()}, **HX)
    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.photo.name.endswith(".webp")
    assert profile.completeness_score >= 20
    logged_client.post(edit("identite"), {"action": "remove_photo"})
    profile.refresh_from_db()
    assert not profile.photo


def test_photo_fake_file_error(logged_client, profile):
    from django.core.files.uploadedfile import SimpleUploadedFile

    fake = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
    response = logged_client.post(edit("identite"), {"action": "photo", "photo": fake})
    assert response.status_code == 200
    assert "pas une photo" in response.content.decode()


class TestServices:
    def test_add_edit_move_delete(self, logged_client, profile):
        for title in ("Fuite", "Chauffe-eau", "Sanitaires"):
            logged_client.post(
                reverse("dashboard:service_add"), {"title": title, "price_label": "dès 5 000 FCFA"}, **HX
            )
        titles = list(profile.services.values_list("title", flat=True))
        assert titles == ["Fuite", "Chauffe-eau", "Sanitaires"]
        third = profile.services.get(title="Sanitaires")
        logged_client.post(reverse("dashboard:service_move", args=[third.pk]), {"direction": "up"}, **HX)
        assert list(profile.services.values_list("title", flat=True)) == ["Fuite", "Sanitaires", "Chauffe-eau"]
        logged_client.post(reverse("dashboard:service_update", args=[third.pk]), {"title": "Salle de bain"}, **HX)
        third.refresh_from_db()
        assert third.title == "Salle de bain"
        logged_client.post(reverse("dashboard:service_delete", args=[third.pk]), **HX)
        assert profile.services.count() == 2
        profile.refresh_from_db()
        assert profile.completeness_score >= 15  # >= 2 services

    def test_max_20(self, logged_client, profile):
        for i in range(MAX_SERVICES):
            ProfileService.objects.create(profile=profile, title=f"S{i}", order=i)
        response = logged_client.post(reverse("dashboard:service_add"), {"title": "Une de trop"}, **HX)
        assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "error"
        assert profile.services.count() == MAX_SERVICES

    def test_get_not_allowed(self, logged_client):
        assert logged_client.get(reverse("dashboard:service_add")).status_code == 405


class TestGallery:
    def test_upload_multiple_caption_move_delete(self, logged_client, profile):
        response = logged_client.post(
            reverse("dashboard:media_add"), {"images": [make_image(name="a.jpg"), make_image(name="b.jpg")]}, **HX
        )
        assert response.status_code == 200
        media = list(profile.media.all())
        assert len(media) == 2
        assert all(m.image.name.endswith(".webp") for m in media)
        assert media[0].width == 1200
        logged_client.post(reverse("dashboard:media_update", args=[media[0].pk]), {"caption": "Avant / après"})
        media[0].refresh_from_db()
        assert media[0].caption == "Avant / après"
        logged_client.post(reverse("dashboard:media_move", args=[media[1].pk]), {"direction": "up"})
        assert list(profile.media.values_list("pk", flat=True)) == [media[1].pk, media[0].pk]
        logged_client.post(reverse("dashboard:media_delete", args=[media[0].pk]))
        assert profile.media.count() == 1

    def test_gallery_max_12(self, logged_client, profile):
        for i in range(12):
            ProfileMedia.objects.create(profile=profile, image=f"x{i}.webp", order=i)
        logged_client.post(reverse("dashboard:media_add"), {"images": [make_image()]})
        assert profile.media.count() == 12

    def test_three_photos_complete_gallery_item(self, logged_client, profile):
        logged_client.post(reverse("dashboard:media_add"), {"images": [make_image(name=f"{i}.jpg") for i in range(3)]})
        profile.refresh_from_db()
        assert profile.media.count() == 3
        assert profile.completeness_score >= 10


class TestLinks:
    def test_only_https(self, logged_client, profile):
        logged_client.post(reverse("dashboard:link_add"), {"kind": "facebook", "url": "http://facebook.com/x"})
        assert profile.links.count() == 0
        logged_client.post(reverse("dashboard:link_add"), {"kind": "facebook", "url": "javascript:alert(1)"})
        assert profile.links.count() == 0
        logged_client.post(reverse("dashboard:link_add"), {"kind": "facebook", "url": "https://facebook.com/x"})
        assert profile.links.count() == 1

    def test_invalid_kind(self, logged_client, profile):
        logged_client.post(reverse("dashboard:link_add"), {"kind": "myspace", "url": "https://x.test"})
        assert profile.links.count() == 0

    def test_delete_and_move(self, logged_client, profile):
        a = ProfileLink.objects.create(profile=profile, kind="website", url="https://a.test", order=0)
        b = ProfileLink.objects.create(profile=profile, kind="website", url="https://b.test", order=1)
        logged_client.post(reverse("dashboard:link_move", args=[b.pk]), {"direction": "up"})
        assert list(profile.links.values_list("pk", flat=True)) == [b.pk, a.pk]
        logged_client.post(reverse("dashboard:link_delete", args=[a.pk]))
        assert list(profile.links.values_list("pk", flat=True)) == [b.pk]
