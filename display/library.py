"""Photo library queries shared by the saver API and the settings page."""
from .models import SaverPhoto
from .options import SEASONS

SEASON_LABELS = dict(SEASONS)


def season_photos(season):
    return [p.image.url for p in SaverPhoto.objects.filter(enabled=True) if p.in_season(season)]


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
