import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.dashboard.services import process_image

from .helpers import make_image


def _decode(content):
    return Image.open(io.BytesIO(content.read()))


def test_reencoded_to_webp_resized_and_exif_stripped():
    upload = make_image()
    with Image.open(io.BytesIO(upload.read())) as original:
        assert original.getexif().get(0x010F) == "SecretCameraMaker"
    upload.seek(0)
    content = process_image(upload, max_side=800)
    raw = content.read()
    assert b"SecretCameraMaker" not in raw
    img = Image.open(io.BytesIO(raw))
    assert img.format == "WEBP"
    assert img.size == (800, 600)
    assert not img.getexif()
    assert "exif" not in img.info
    assert content.name.endswith(".webp")


def test_png_with_alpha_is_accepted():
    img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    content = process_image(SimpleUploadedFile("a.png", buf.getvalue(), content_type="image/png"))
    assert _decode(content).format == "WEBP"


def test_small_image_not_upscaled():
    content = process_image(make_image(size=(300, 200)))
    assert _decode(content).size == (300, 200)


def test_fake_image_refused():
    fake = SimpleUploadedFile("evil.jpg", b"<?php echo 'hi'; ?>", content_type="image/jpeg")
    with pytest.raises(ValidationError):
        process_image(fake)


def test_too_big_refused():
    big = SimpleUploadedFile("big.jpg", b"0" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
    with pytest.raises(ValidationError, match="5 Mo"):
        process_image(big)
