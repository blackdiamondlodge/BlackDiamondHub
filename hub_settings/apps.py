from django.apps import AppConfig


class HubSettingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hub_settings"
    verbose_name = "Hub settings"

    def ready(self):
        from bdh_sdk.settings import set_store
        from bdh_sdk.storage import set_state_backend
        from django.db.models.signals import post_delete, post_save

        from . import store
        from .models import AppSetting
        from .state import DatabaseStateBackend

        set_store(store.lookup)
        set_state_backend(DatabaseStateBackend())
        post_save.connect(store.clear, sender=AppSetting, dispatch_uid="hub_settings_clear_save")
        post_delete.connect(store.clear, sender=AppSetting, dispatch_uid="hub_settings_clear_delete")
