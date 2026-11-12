"""Photo library queries shared by the saver API and the settings page."""
from datetime import timezone

from .models import SaverPhoto
from .options import SEASONS

SEASON_LABELS = dict(SEASONS)


def caption(photo):
    """e.g. "March 2024" from when the photo was taken, else ""."""
    taken = photo.taken_at
    if not taken:
        return ""
    taken = taken.astimezone(timezone.utc)
    return f"{taken.strftime('%B')} {taken.year}"


def season_photos(season, captions=False):
    """Enabled photos for ``season`` as ``{"url", "caption"}``; captions are blank unless asked for."""
    return [{"url": p.image.url, "caption": caption(p) if captions else ""}
            for p in SaverPhoto.objects.filter(enabled=True) if p.in_season(season)]


def photo_json(photo):
    return {
        "id": photo.id,
        "name": photo.name,
        "thumb": photo.thumb.url,
        "image": photo.image.url,
        "seasons": photo.seasons,
        "enabled": photo.enabled,
        "tag": " · ".join(SEASON_LABELS[s] for s in photo.seasons) if photo.seasons else "Any season",
    }
