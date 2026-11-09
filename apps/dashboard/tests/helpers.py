import io
import re

from PIL import Image


def code_from(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)


def make_image(fmt: str = "JPEG", size=(1600, 1200), *, exif: bool = True, name: str = "photo.jpg"):
    """An in-memory image, optionally with EXIF (GPS-like data) to check stripping."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    img = Image.new("RGB", size, (10, 127, 125))
    buf = io.BytesIO()
    kwargs = {}
    if exif and fmt == "JPEG":
        data = Image.Exif()
        data[0x010F] = "SecretCameraMaker"  # Make
        data[0x0131] = "SecretSoftware"  # Software
        data[0x0112] = 1  # Orientation
        kwargs["exif"] = data.tobytes()
    img.save(buf, format=fmt, **kwargs)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png"}.get(fmt, "application/octet-stream")
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)
