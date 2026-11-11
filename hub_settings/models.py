from django.conf import settings
from django.db import models


class AppSetting(models.Model):
    """A value saved on the Settings page for one app's declared Setting.

    It wins over the environment when the app reads the setting with
    ``bdh_sdk.settings.app_setting``. Deleting the row falls back to the
    environment or the declared default again.
    """

    app_id = models.CharField(max_length=64)
    key = models.CharField(max_length=64)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["app_id", "key"], name="hub_settings_unique_app_key"),
        ]
        ordering = ["app_id", "key"]

    def __str__(self):
        return f"{self.app_id}.{self.key} = {self.value!r}"


class AppState(models.Model):
    """Something an app remembers between runs, via ``bdh_sdk.storage.app_state``."""

    app_id = models.CharField(max_length=64)
    key = models.CharField(max_length=128)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["app_id", "key"], name="hub_settings_unique_state_key"),
        ]
        ordering = ["app_id", "key"]

    def __str__(self):
        return f"{self.app_id}.{self.key} = {self.value!r}"
