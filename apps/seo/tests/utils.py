"""Test helpers: several indexable profiles need distinct bios (duplicate bios are not indexable)."""

import itertools
import json
import re

from tests.factories import make_complete_profile

_counter = itertools.count(1)

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def unique_bio() -> str:
    n = next(_counter)
    return " ".join(f"mot{n}x{j}" for j in range(70))


def indexable_profile(**kwargs):
    kwargs.setdefault("bio", unique_bio())
    profile = make_complete_profile(**kwargs)
    assert profile.is_indexable, "test helper must produce an indexable profile"
    return profile


def jsonld_blocks(html: str) -> list:
    return [json.loads(raw) for raw in JSONLD_RE.findall(html)]


def meta_content(html: str, attr: str, name: str) -> str | None:
    match = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)"', html)
    return match.group(1) if match else None
