import secrets
from datetime import timedelta

from bdh_sdk.storage import app_media
from django.db import models
from django.utils import timezone

UPLOAD_MINUTES = 10


def media():
    return app_media("display")


class SaverPhoto(models.Model):
    """A photo in the screensaver library. No seasons means every season."""

    image = models.ImageField(storage=media, upload_to="photos/")
    thumb = models.ImageField(storage=media, upload_to="thumbs/")
    name = models.CharField(max_length=120, blank=True)
    seasons = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    taken_at = models.DateTimeField(null=True, blank=True)
    link = models.ForeignKey("UploadLink", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="photos")

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def in_season(self, season):
        return not self.seasons or season in self.seasons

    def delete(self, *args, **kwargs):
        for field in (self.image, self.thumb):
            if field:
                field.storage.delete(field.name)
        return super().delete(*args, **kwargs)


def _key():
    return secrets.token_urlsafe(18)


def _expiry():
    return timezone.now() + timedelta(minutes=UPLOAD_MINUTES)


class UploadLink(models.Model):
    """A short-lived link a phone uses to add photos. The first phone to open it claims it."""

    key = models.CharField(max_length=32, unique=True, default=_key)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_expiry)
    claim = models.CharField(max_length=48, blank=True)

    def live(self):
        return timezone.now() < self.expires_at

    def seconds_left(self):
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))
