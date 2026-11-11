from django.apps import AppConfig


class HubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hub"
    verbose_name = "Black Diamond Hub platform"

    def ready(self):
        from bdh_sdk.alerts import set_sender

        from . import alerts

        set_sender(alerts.send)
