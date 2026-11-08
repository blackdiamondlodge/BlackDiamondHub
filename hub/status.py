"""Runs app status and shortcut hooks for the homepage.

Hooks are called in a shared thread pool with a deadline, so one slow or
broken app can't hold up the homepage. Results are cached; when a hook fails
or times out the last good result is served marked ``stale``.
"""
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from importlib import import_module

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from .modes import plugins
from .plugins import INFO, STATUS_LEVELS, Shortcut, Status, Stay

logger = logging.getLogger(__name__)

STATUS_TTL = 60
SHORTCUTS_TTL = 60
STAY_TTL = 60
LAST_GOOD_TTL = 6 * 3600
TIMEOUT = 6.0
# Every homepage request waits on the stay hook, so give up on it sooner.
STAY_TIMEOUT = 3.0

_SLUG = re.compile(r"[-a-zA-Z0-9_]+")

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hub-hook")
_inflight = {}
_inflight_lock = threading.Lock()


class ShortcutNotFound(Exception):
    pass


def _resolve(path):
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


def _status_value(result):
    if result is None:
        return None
    if isinstance(result, str):
        result = Status(result)
    if not isinstance(result, Status):
        raise TypeError(f"status hook returned {type(result).__name__}")
    level = result.level if result.level in STATUS_LEVELS else INFO
    return {"text": result.text, "level": level}


def _shortcuts_value(result):
    items = []
    for sc in result or ():
        if not isinstance(sc, Shortcut):
            raise TypeError(f"shortcuts hook returned {type(sc).__name__}")
        if not _SLUG.fullmatch(sc.id):
            logger.warning("Skipping shortcut with invalid id %r", sc.id)
            continue
        items.append({
            "id": sc.id,
            "title": sc.title,
            "icon": sc.icon,
            "order": sc.order,
            "modes": sorted(sc.modes),
        })
    return items


def _stay_value(result):
    if result is None:
        return None
    if not isinstance(result, Stay):
        raise TypeError(f"stay hook returned {type(result).__name__}")
    return {"guest": result.guest, "arrival": result.arrival, "checkout": result.checkout}


def _fresh_key(kind, plugin_id):
    return f"hub:{kind}:{plugin_id}"


def _last_key(kind, plugin_id):
    return f"hub:{kind}:{plugin_id}:last"


def _run_hook(kind, plugin_id, path, convert, ttl):
    try:
        value = convert(_resolve(path)())
        entry = {"value": value, "updated": time.time()}
        cache.set(_fresh_key(kind, plugin_id), entry, ttl)
        cache.set(_last_key(kind, plugin_id), entry, LAST_GOOD_TTL)
        return entry
    finally:
        close_old_connections()


def _submit(kind, plugin_id, path, convert, ttl):
    """Start the hook unless the same one is already running."""
    key = _fresh_key(kind, plugin_id)
    with _inflight_lock:
        future = _inflight.get(key)
        if future is None or future.done():
            future = _executor.submit(_run_hook, kind, plugin_id, path, convert, ttl)
            _inflight[key] = future
    return future


def _gather(jobs, timeout):
    """Run (kind, plugin_id, path, convert, ttl) jobs; return {(kind, id): entry}.

    Entries are ``{"value", "updated", "stale"}``. Jobs with no fresh result
    and no last good result are left out.
    """
    results, pending = {}, {}
    for kind, plugin_id, path, convert, ttl in jobs:
        hit = cache.get(_fresh_key(kind, plugin_id))
        if hit is not None:
            results[(kind, plugin_id)] = {**hit, "stale": False}
        else:
            pending[(kind, plugin_id)] = _submit(kind, plugin_id, path, convert, ttl)

    if pending:
        wait(pending.values(), timeout=timeout)
    for (kind, plugin_id), future in pending.items():
        if future.done() and future.exception() is None:
            results[(kind, plugin_id)] = {**future.result(), "stale": False}
            continue
        if future.done():
            logger.warning("%s hook for %s failed: %s", kind, plugin_id, future.exception())
        else:
            logger.warning("%s hook for %s timed out", kind, plugin_id)
        last = cache.get(_last_key(kind, plugin_id))
        if last is not None:
            results[(kind, plugin_id)] = {**last, "stale": True}
    return results


def _visible(spec, mode):
    return any(mode in tile.modes for tile in spec.tiles)


def _offered(shortcuts, mode):
    return [sc for sc in shortcuts if mode in sc["modes"]]


def home_data(mode, timeout=TIMEOUT):
    """Status lines and shortcuts for the homepage in ``mode``."""
    specs = plugins()
    jobs = [
        ("status", s.id, s.status, _status_value, STATUS_TTL)
        for s in specs if s.status and _visible(s, mode)
    ] + [
        ("shortcuts", s.id, s.shortcuts, _shortcuts_value, SHORTCUTS_TTL)
        for s in specs if s.shortcuts
    ]
    results = _gather(jobs, timeout)

    status = {}
    shortcuts = []
    for (kind, plugin_id), entry in results.items():
        if kind == "status":
            if entry["value"] is not None:
                status[plugin_id] = {
                    **entry["value"],
                    "updated": entry["updated"],
                    "stale": entry["stale"],
                }
        else:
            for sc in _offered(entry["value"], mode):
                shortcuts.append({
                    "plugin": plugin_id,
                    "id": sc["id"],
                    "title": sc["title"],
                    "icon": sc["icon"],
                    "order": sc["order"],
                })
    shortcuts.sort(key=lambda sc: (sc["order"], sc["title"]))
    return {"status": status, "shortcuts": shortcuts}


def current_stay(timeout=STAY_TIMEOUT, now=None):
    """The stay reported by the first app with a stay hook, or None.

    When a hook fails its last good answer is used, but never past that
    stay's checkout, so a broken hook can't hold the homepage in guest mode.
    """
    specs = [s for s in plugins() if s.stay]
    if not specs:
        return None
    results = _gather(
        [("stay", s.id, s.stay, _stay_value, STAY_TTL) for s in specs], timeout
    )
    now = now or timezone.now()
    for spec in specs:
        entry = results.get(("stay", spec.id))
        stay = entry["value"] if entry else None
        if stay is None:
            continue
        if stay["checkout"] is not None and stay["checkout"] <= now:
            continue
        return stay
    return None


def run_shortcut(plugin_id, shortcut_id, mode, timeout=TIMEOUT):
    """Run a shortcut if ``plugin_id`` offers it in ``mode``.

    Raises ShortcutNotFound when it isn't offered; anything the app's
    handler raises propagates.
    """
    spec = next((s for s in plugins() if s.id == plugin_id and s.shortcuts), None)
    if spec is None:
        raise ShortcutNotFound(plugin_id)
    entry = _gather(
        [("shortcuts", spec.id, spec.shortcuts, _shortcuts_value, SHORTCUTS_TTL)],
        timeout,
    ).get(("shortcuts", spec.id))
    offered = _offered(entry["value"], mode) if entry else []
    if not any(sc["id"] == shortcut_id for sc in offered):
        raise ShortcutNotFound(f"{plugin_id}/{shortcut_id}")

    message = _resolve(spec.run_shortcut)(shortcut_id)
    # The shortcut probably changed the status line and which shortcuts apply.
    cache.delete(_fresh_key("status", spec.id))
    cache.delete(_fresh_key("shortcuts", spec.id))
    return message
