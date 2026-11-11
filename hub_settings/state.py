"""Database backend for ``bdh_sdk.storage.app_state``."""


def _model():
    from .models import AppState

    return AppState


class DatabaseStateBackend:
    def get(self, app_id, key):
        AppState = _model()
        try:
            return AppState.objects.values_list("value", flat=True).get(app_id=app_id, key=key)
        except AppState.DoesNotExist:
            raise KeyError(key) from None

    def set(self, app_id, key, value):
        _model().objects.update_or_create(app_id=app_id, key=key, defaults={"value": value})

    def delete(self, app_id, key):
        _model().objects.filter(app_id=app_id, key=key).delete()

    def keys(self, app_id):
        return list(_model().objects.filter(app_id=app_id).order_by("key").values_list("key", flat=True))