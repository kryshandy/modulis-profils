"""Pure helpers: titles, descriptions, robots and JSON-LD escaping."""

import json

import pytest

from apps.seo import jsonld
from apps.seo.meta import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    TITLE_MAX,
    clean_text,
    profile_alt,
    profile_description,
    profile_title,
    robots_content,
    truncate,
)
from tests.factories import ProfileFactory, TradeFactory


def test_title_format():
    assert profile_title("Paul Ndongo", "Plombier", "Douala") == "Paul Ndongo – Plombier à Douala"
    assert profile_title("Paul Ndongo", "Plombier") == "Paul Ndongo – Plombier"
    assert profile_title("Paul Ndongo", "", "Douala") == "Paul Ndongo – Douala"
    assert profile_title("Paul Ndongo") == "Paul Ndongo"


def test_title_truncates_name_first():
    name = "Jean-Baptiste Emmanuel Nkoulou Mbarga Atangana Essomba"
    title = profile_title(name, "Plombier", "Douala")
    assert len(title) <= TITLE_MAX
    assert title.endswith("… – Plombier à Douala")


def test_title_drops_city_then_hard_truncates():
    job = "Développeuse web et mobile spécialisée e-commerce"
    title = profile_title("Aïcha Bello", job, "Yaoundé")
    assert len(title) <= TITLE_MAX
    assert "Yaoundé" not in title
    assert len(profile_title("x" * 100)) == TITLE_MAX


@pytest.mark.parametrize(
    "bio",
    [
        "",
        "Courte bio.",
        "Plombier sérieux. " * 30,
        "<p>Du <b>HTML</b> &amp; des   espaces</p>\n" * 10,
        "Motextrêmementlongsansespace" * 20,
    ],
)
def test_description_length(bio):
    text = profile_description("Paul Ndongo", "Plombier", "Douala", bio, ["Fuites", "Chauffe-eau"])
    assert DESCRIPTION_MIN <= len(text) <= DESCRIPTION_MAX
    assert "<" not in text
    assert "  " not in text


def test_description_template_when_no_bio():
    text = profile_description("Paul Ndongo", "Plombier", "Douala", "", ["Fuites", "Chauffe-eau"])
    assert text.startswith("Paul Ndongo, plombier à Douala. Services : Fuites, Chauffe-eau.")


def test_description_never_invents_services():
    text = profile_description("Paul", "", "", "", [])
    assert text.startswith("Paul. Contact WhatsApp.")
    assert "Services" not in text
    assert len(text) <= DESCRIPTION_MAX


def test_helpers():
    assert clean_text("<b>a</b>&amp;\n b") == "a& b"
    assert truncate("un deux trois quatre cinq", 16) == "un deux trois…"
    assert truncate("court", 16) == "court"
    assert robots_content(True) == "index, follow"
    assert robots_content(False) == "noindex, follow"
    assert profile_alt("Paul", "Plombier", "Douala") == "Réalisation de Paul, plombier à Douala"


def test_dumps_escapes_html_sensitive_characters():
    raw = jsonld.dumps({"bio": "</script><script>alert('x')</script> & co"})
    assert "<" not in raw
    assert ">" not in raw
    assert "&" not in raw
    assert "\\u003c/script\\u003e" in raw
    assert json.loads(raw)["bio"] == "</script><script>alert('x')</script> & co"


@pytest.mark.django_db
def test_schema_type_selection():
    business = ProfileFactory()
    assert jsonld.schema_type_for(business) == "Plumber"
    liberal = TradeFactory(
        name="Juriste Test",
        slug="juriste-test",
        plural_slug="juristes-test",
        plural_name="Juristes",
        schema_type="Person",
    )
    person = ProfileFactory(trade=liberal)
    assert jsonld.schema_type_for(person) == "Person"
    assert jsonld.schema_type_for(ProfileFactory(trade=None, kind="person")) == "Person"
    assert jsonld.schema_type_for(ProfileFactory(trade=None, kind="business")) == "LocalBusiness"
    bogus = TradeFactory(
        name="Bizarre Test",
        slug="bizarre-test",
        plural_slug="bizarres-test",
        plural_name="Bizarres",
        schema_type="<script>",
    )
    assert jsonld.schema_type_for(ProfileFactory(trade=bogus)) == "LocalBusiness"


@pytest.mark.django_db
def test_person_entity_has_job_title_and_no_area_served():
    liberal = TradeFactory(
        name="Juriste Test",
        slug="juriste-test",
        plural_slug="juristes-test",
        plural_name="Juristes",
        schema_type="Person",
    )
    profile = ProfileFactory(trade=liberal, display_name="Maître Test")
    profile.links.create(kind="other", url="javascript:alert(1)")
    profile.links.create(kind="website", url="https://exemple.test")
    entity = jsonld.profile_entity(profile, image_url="/x.png")
    assert entity["@type"] == "Person"
    assert entity["jobTitle"] == "Juriste Test"
    assert "areaServed" not in entity
    assert entity["sameAs"] == ["https://exemple.test"]
    assert entity["image"] == "https://profils.test/x.png"
