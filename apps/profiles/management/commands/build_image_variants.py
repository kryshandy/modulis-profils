"""Backfill responsive variants (-160/-400/-800.webp) and sizes for images uploaded before they existed.

Usage: python manage.py build_image_variants   (idempotent: existing variants are rebuilt)
"""

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, UnidentifiedImageError

from apps.profiles import images
from apps.profiles.models import Profile, ProfileMedia


def _rebuild(fieldfile) -> tuple[int, int] | None:
    storage = fieldfile.storage
    try:
        with storage.open(fieldfile.name, "rb") as handle, Image.open(handle) as img:
            img.load()
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            for width in images.variant_widths(img.width):
                height = max(1, round(img.height * width / img.width))
                name = images.variant_name(fieldfile.name, width)
                storage.delete(name)
                storage.save(
                    name, ContentFile(images.encode_webp(img.resize((width, height), Image.Resampling.LANCZOS)))
                )
            return img.size
    except (FileNotFoundError, OSError, UnidentifiedImageError):
        return None


class Command(BaseCommand):
    help = "Génère les variantes responsives des photos de profil et de galerie déjà en ligne."

    def handle(self, *args, **options):
        done = 0
        for profile in Profile.objects.exclude(photo="").exclude(status=Profile.Status.DELETED).iterator():
            size = _rebuild(profile.photo)
            if size:
                Profile.objects.filter(pk=profile.pk).update(photo_width=size[0], photo_height=size[1])
                done += 1
        for media in ProfileMedia.objects.exclude(image="").iterator():
            size = _rebuild(media.image)
            if size:
                ProfileMedia.objects.filter(pk=media.pk).update(width=size[0], height=size[1])
                done += 1
        self.stdout.write(self.style.SUCCESS(f"{done} image(s) traitée(s)."))
