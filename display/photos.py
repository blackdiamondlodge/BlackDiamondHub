"""Turning an uploaded file into a library photo."""
import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import SaverPhoto

MAX_SIDE = 2560
THUMB_SIDE = 480
MAX_BYTES = 40 * 1024 * 1024


class BadPhoto(ValueError):
    pass


def _jpeg(img, side, quality):
    img = img.copy()
    img.thumbnail((side, side), Image.LANCZOS)
    out = BytesIO()
    # Saving without exif= drops the EXIF block (GPS, camera) once orientation is applied.
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def add_photo(upload, seasons=(), link=None):
    """Store ``upload`` as a library photo: upright, at most 2560px, no EXIF, with a thumbnail."""
    if upload.size > MAX_BYTES:
        raise BadPhoto("That file is too large.")
    try:
        with Image.open(upload) as src:
            img = ImageOps.exif_transpose(src)
            img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise BadPhoto("That isn't a photo the hub can read.") from None

    stem = os.path.splitext(os.path.basename(upload.name or "photo"))[0][:80] or "photo"
    photo = SaverPhoto(name=stem, seasons=list(seasons), link=link)
    photo.image.save(f"{stem}.jpg", ContentFile(_jpeg(img, MAX_SIDE, 85)), save=False)
    photo.thumb.save(f"{stem}.jpg", ContentFile(_jpeg(img, THUMB_SIDE, 80)), save=False)
    photo.save()
    return photo
