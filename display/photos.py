"""Turning an uploaded file into a library photo."""
import os
from datetime import datetime, timezone
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import SaverPhoto

MAX_SIDE = 2560
THUMB_SIDE = 480
MAX_BYTES = 40 * 1024 * 1024
EXIF_IFD, DATE_TAKEN, DATE_TIME = 0x8769, 36867, 306


class BadPhoto(ValueError):
    pass


def _jpeg(img, side, quality):
    img = img.copy()
    img.thumbnail((side, side), Image.LANCZOS)
    out = BytesIO()
    # Saving without exif= drops the EXIF block (GPS, camera) once orientation is applied.
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def taken_at(img):
    """When the photo was taken, from its EXIF date, or None."""
    try:
        exif = img.getexif()
        text = exif.get_ifd(EXIF_IFD).get(DATE_TAKEN) or exif.get(DATE_TIME)
        stamp = datetime.strptime(str(text).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError, AttributeError, OSError, KeyError):
        return None
    # EXIF has no zone; store the camera's wall clock as UTC so the month never shifts.
    return stamp.replace(tzinfo=timezone.utc)


def add_photo(upload, seasons=(), link=None):
    """Store ``upload`` as a library photo: upright, at most 2560px, no EXIF, with a thumbnail."""
    if upload.size > MAX_BYTES:
        raise BadPhoto("That file is too large.")
    try:
        with Image.open(upload) as src:
            taken = taken_at(src)
            img = ImageOps.exif_transpose(src)
            img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise BadPhoto("That isn't a photo the hub can read.") from None

    stem = os.path.splitext(os.path.basename(upload.name or "photo"))[0][:80] or "photo"
    photo = SaverPhoto(name=stem, seasons=list(seasons), link=link, taken_at=taken)
    photo.image.save(f"{stem}.jpg", ContentFile(_jpeg(img, MAX_SIDE, 85)), save=False)
    photo.thumb.save(f"{stem}.jpg", ContentFile(_jpeg(img, THUMB_SIDE, 80)), save=False)
    photo.save()
    return photo
