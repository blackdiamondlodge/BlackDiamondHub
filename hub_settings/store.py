"""The database-backed store that ``bdh_sdk.settings.app_setting`` checks first.

Saved values are read in one query and cached in-process. Saving or deleting
an ``AppSetting`` clears the cache; the TTL covers changes made by another
process (e.g. a management command).
"""
import logging
import threading
import time

from bdh_sdk.settings import app_setting

log = logging.getLogger(__name__)

TTL = 30.0

_lock = threading.Lock()
_cache = None
_loaded_at = 0.0
_bypass = threading.local()


def _load():
    from .models import AppSetting

    return {(row.app_id, row.key): row.value for row in AppSetting.objects.all()}


def _values():
    global _cache, _loaded_at
    with _lock:
        if _cache is not None and time.monotonic() - _loaded_at < TTL:
            return _cache
    try:
        values = _load()
    except Exception as exc:
        # Before migrations, without a database, or from async code.
        log.debug("settings store unavailable: %s", exc)
        return _cache or {}
    with _lock:
        _cache, _loaded_at = values, time.monotonic()
    return values


def lookup(app_id, key):
    if getattr(_bypass, "on", False):
        raise KeyError(key)
    return _values()[(app_id, key)]


def clear(**_kwargs):
    global _cache
    with _lock:
        _cache = None


def saved(app_id):
    """Saved values for ``app_id``, read fresh from the database."""
    from .models import AppSetting

    return dict(AppSetting.objects.filter(app_id=app_id).values_list("key", "value"))


def fallback(app_id, setting):
    """What ``setting`` would be without a saved value (environment or default)."""
    _bypass.on = True
    try:
        value = app_setting(app_id, setting.key, setting.default)
    finally:
        _bypass.on = False
    if isinstance(value, str):
        try:
            return setting.parse(value)
        except ValueError:
            return value
    return value
