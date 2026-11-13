"""Cover image (a gallery photo in the big visual) and gallery `sizes` matching the real grid."""

import re

import pytest
from django.urls import reverse

from apps.profiles.models import Profile, ProfileMedia
from apps.profiles.services import set_cover
from apps.public.responsive import gallery_sizes
from apps.seo.tests.utils import indexable_profile
from apps.themes import services
from apps.themes.models import Theme
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def use_layout(profile, layout):
    services.assign_theme(profile, Theme.objects.filter(layout=layout).first())


def add_photo(profile, i=0, width=1200, height=800):
    return ProfileMedia.objects.create(
        profile=profile, image=f"profiles/{profile.pk}/gallery/{i}.webp", width=width, height=height, order=i
    )


# --- gallery sizes ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "count", "expected"),
    [
        (0, 1, "(min-width: 84rem) 80rem, (min-width: 40rem) 100vw, 100vw"),
        (0, 2, "(min-width: 84rem) 40rem, (min-width: 40rem) 50vw, 50vw"),
        (3, 4, "(min-width: 84rem) 40rem, (min-width: 40rem) 50vw, 50vw"),
        (0, 3, "(min-width: 84rem) 53rem, (min-width: 40rem) 67vw, 100vw"),
        (1, 3, "(min-width: 84rem) 27rem, (min-width: 40rem) 33vw, 50vw"),
        (4, 5, "(min-width: 84rem) 40rem, (min-width: 40rem) 50vw, 50vw"),
        (0, 8, "(min-width: 84rem) 53rem, (min-width: 40rem) 67vw, 100vw"),
        (7, 8, "(min-width: 84rem) 27rem, (min-width: 40rem) 33vw, 50vw"),
    ],
)
def test_gallery_sizes_follow_the_grid(index, count, expected):
    assert gallery_sizes(index, count) == expected


def test_gallery_never_announces_a_thumbnail_width_on_desktop(client):
    profile = indexable_profile()
    for i in range(4):
        add_photo(profile, i)
    body = client.get(f"/{profile.slug}").content.decode()
    imgs = re.findall(r"<img src=\"/media/profiles/[^\"]+gallery[^>]+>", body)
    assert len(imgs) == 4
    assert all('sizes="(min-width: 84rem) 40rem, (min-width: 40rem) 50vw, 50vw"' in img for img in imgs)
    assert "14rem" not in body


# --- cover service ------------------------------------------------------------------------------


def test_set_cover_and_clear():
    profile = ProfileFactory()
    media = add_photo(profile)
    set_cover(profile, media.pk)
    assert Profile.objects.get(pk=profile.pk).cover_id == media.pk
    set_cover(profile, None)
    assert Profile.objects.get(pk=profile.pk).cover_id is None


def test_cannot_use_another_page_photo_as_cover():
    profile, other = ProfileFactory(), ProfileFactory()
    foreign = add_photo(other)
    with pytest.raises(ProfileMedia.DoesNotExist):
        set_cover(profile, foreign.pk)


def test_deleting_the_cover_photo_clears_the_cover():
    from apps.profiles.services import delete_media

    profile = ProfileFactory()
    media = add_photo(profile)
    set_cover(profile, media.pk)
    delete_media(profile, media.pk)
    assert Profile.objects.get(pk=profile.pk).cover_id is None


# --- editor -------------------------------------------------------------------------------------


def test_editor_toggles_cover(logged_client, profile):
    media = add_photo(profile)
    url = reverse("dashboard:media_cover", args=[media.pk])
    response = logged_client.post(url)
    assert response.status_code in (200, 302)
    assert Profile.objects.get(pk=profile.pk).cover_id == media.pk
    page = logged_client.get(reverse("dashboard:edit", args=["galerie"])).content.decode()
    assert 'aria-pressed="true"' in page
    logged_client.post(url)
    assert Profile.objects.get(pk=profile.pk).cover_id is None


def test_editor_refuses_foreign_photo(logged_client):
    foreign = add_photo(ProfileFactory())
    assert logged_client.post(reverse("dashboard:media_cover", args=[foreign.pk])).status_code == 404


# --- public rendering ---------------------------------------------------------------------------


def test_signature_slab_shows_cover_instead_of_initials(client):
    profile = indexable_profile()
    media = add_photo(profile)
    use_layout(profile, "cover_color")
    body = client.get(f"/{profile.slug}").content.decode()
    assert "t-sig__mono" in body and "t-sig__img" not in body
    set_cover(profile, media.pk)
    body = client.get(f"/{profile.slug}").content.decode()
    slab = re.search(r'<span class="t-sig__slab t-sig__slab--img">.*?</span>', body, re.S).group(0)
    assert f"/media/profiles/{profile.pk}/gallery/0.webp" in slab
    assert 'sizes="(min-width: 48rem) 27rem, 20rem"' in slab or "srcset" not in slab
    assert 'width="1200" height="800"' in slab
    assert "t-sig__mono" not in body


@pytest.mark.parametrize("layout", ["magazine", "split_photo"])
def test_image_first_layouts_use_cover_in_their_frame(client, layout):
    profile = indexable_profile()
    Profile.objects.filter(pk=profile.pk).update(photo=f"profiles/{profile.pk}/photo.webp")
    media = add_photo(profile)
    use_layout(profile, layout)
    set_cover(profile, media.pk)
    body = client.get(f"/{profile.slug}").content.decode()
    head = re.search(r'<img class="profile-head__photo"[^>]*>', body).group(0)
    assert f"/media/profiles/{profile.pk}/gallery/0.webp" in head


@pytest.mark.parametrize("layout", ["editorial", "centered", "card"])
def test_portrait_layouts_keep_the_portrait(client, layout):
    profile = indexable_profile()
    Profile.objects.filter(pk=profile.pk).update(photo=f"profiles/{profile.pk}/photo.webp")
    media = add_photo(profile)
    use_layout(profile, layout)
    set_cover(profile, media.pk)
    body = client.get(f"/{profile.slug}").content.decode()
    head = re.search(r'<img class="profile-head__photo"[^>]*>', body).group(0)
    assert f"/media/profiles/{profile.pk}/photo.webp" in head
