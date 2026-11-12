"""Runs app status and shortcut hooks for the homepage.

Hooks are called in a shared thread pool with a deadline, so one slow or
broken app can't hold up the homepage. Results are cached; when a hook fails
or times out the last good result is served marked ``stale``.

The homepage also serves the last good result straight away while a slow
hook refreshes in the background (marked ``refreshing``), so returning to it
after a while in another app doesn't wait on every hook.
"""
import inspect
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from importlib import import_module

from django.core.cache import cache
from django.db import close_old_connections
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .modes import plugins
from .plugins import (
    ALL_MODES, GUEST, INFO, STATUS_LEVELS, WARN,
    Action, Card, Reading, Shortcut, Status, StatusRow, Stay,
)

logger = logging.getLogger(__name__)

STATUS_TTL = 60
# Fastest a status may ask the homepage to poll (Status.refresh).
MIN_REFRESH = 2
SHORTCUTS_TTL = 60
STAY_TTL = 60
CARD_TTL = 60
LAST_GOOD_TTL = 6 * 3600
TIMEOUT = 6.0
# Every homepage request waits on the stay hook, so give up on it sooner.
STAY_TIMEOUT = 3.0
# How long the homepage waits for a hook before serving its last good result.
REFRESH_GRACE = 0.3

_SLUG = re.compile(r"[-a-zA-Z0-9_]+")

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hub-hook")
_inflight = {}
_inflight_lock = threading.Lock()


class ShortcutNotFound(Exception):
    pass


class ActionNotFound(Exception):
    pass


def _resolve(path):
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


def _image_url(url):
    """``url`` if the screen's browser may load it as an image, else ""."""
    url = str(url or "")
    return url if re.match(r"(https?://|/(?!/))", url) else ""


def _actions_value(actions):
    items = []
    for a in actions:
        if not isinstance(a, Action):
            raise TypeError(f"status action is {type(a).__name__}")
        if not _SLUG.fullmatch(a.id):
            logger.warning("Skipping status action with invalid id %r", a.id)
            continue
        items.append({"id": a.id, "icon": a.icon, "label": a.label,
                      "primary": bool(a.primary)})
    return items


def _status_value(result):
    if result is None:
        return None
    if isinstance(result, str):
        result = Status(result)
    if not isinstance(result, Status):
        raise TypeError(f"status hook returned {type(result).__name__}")
    level = result.level if result.level in STATUS_LEVELS else INFO
    value = {"text": result.text, "level": level}
    rows = []
    for row in result.rows:
        if not isinstance(row, StatusRow):
            raise TypeError(f"status row is {type(row).__name__}")
        if not _SLUG.fullmatch(row.id):
            logger.warning("Skipping status row with invalid id %r", row.id)
            continue
        rows.append({
            "id": row.id,
            "title": row.title,
            "detail": row.detail,
            "image": _image_url(row.image),
            "dimmed": bool(row.dimmed),
            "actions": _actions_value(row.actions),
        })
    actions = _actions_value(result.actions)
    if rows:
        value["rows"] = rows
    if actions:
        value["actions"] = actions
    if result.refresh:
        value["refresh"] = max(MIN_REFRESH, int(result.refresh))
    return value


def _status_ttl(value):
    """Cache a status no longer than it asked the homepage to poll."""
    refresh = (value or {}).get("refresh")
    return min(STATUS_TTL, refresh) if refresh else STATUS_TTL


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
    return {"guest": result.guest, "arrival": result.arrival,
            "checkout": result.checkout, "owner": bool(result.owner)}


def _card_value(result):
    if result is None:
        return None
    if not isinstance(result, Card):
        raise TypeError(f"card hook returned {type(result).__name__}")
    url = None
    if result.url_name:
        try:
            url = reverse(result.url_name)
        except NoReverseMatch:
            logger.warning("Card links to unknown URL name %r", result.url_name)
    readings = []
    for r in result.readings:
        if not isinstance(r, Reading):
            raise TypeError(f"card reading is {type(r).__name__}")
        readings.append({"label": r.label, "value": r.value, "unit": r.unit})
    return {
        "title": result.title,
        "detail": result.detail,
        "readings": readings,
        "alerts": [str(a) for a in result.alerts],
        "url": url,
        "level": result.level if result.level in STATUS_LEVELS else INFO,
    }


def _fresh_key(kind, plugin_id, mode=None):
    return f"hub:{kind}:{plugin_id}" + (f":{mode}" if mode else "")


def _last_key(kind, plugin_id, mode=None):
    return _fresh_key(kind, plugin_id, mode) + ":last"


def _failed_key(kind, plugin_id, mode=None):
    return _fresh_key(kind, plugin_id, mode) + ":failed"


def _takes_mode(path):
    """True when the hook at ``path`` accepts a ``mode`` argument."""
    try:
        return "mode" in inspect.signature(_resolve(path)).parameters
    except Exception:
        return False


def _run_hook(kind, plugin_id, path, convert, ttl, mode=None):
    try:
        hook = _resolve(path)
        value = convert(hook(mode=mode) if mode else hook())
    except Exception:
        # Remembered so a background refresh that fails still shows as stale.
        cache.set(_failed_key(kind, plugin_id, mode), True, LAST_GOOD_TTL)
        raise
    else:
        entry = {"value": value, "updated": time.time()}
        cache.set(_fresh_key(kind, plugin_id, mode), entry,
                  ttl(value) if callable(ttl) else ttl)
        cache.set(_last_key(kind, plugin_id, mode), entry, LAST_GOOD_TTL)
        cache.delete(_failed_key(kind, plugin_id, mode))
        return entry
    finally:
        close_old_connections()


def _submit(kind, plugin_id, path, convert, ttl, mode=None):
    """Start the hook unless the same one is already running."""
    key = _fresh_key(kind, plugin_id, mode)
    with _inflight_lock:
        future = _inflight.get(key)
        if future is None or future.done():
            future = _executor.submit(_run_hook, kind, plugin_id, path, convert, ttl, mode)
            _inflight[key] = future
    return future


def _gather(jobs, timeout, grace=None):
    """Run (kind, plugin_id, path, convert, ttl[, mode]) jobs; return {(kind, id): entry}.

    A job with a mode calls its hook with ``mode=`` and is cached per mode.
    Entries are ``{"value", "updated", "stale"}``. Jobs with no fresh result
    and no last good result are left out.

    With ``grace``, a hook still running after ``grace`` seconds is served
    from its last good result (if any) marked ``refreshing`` and finishes in
    the background; only hooks with no last good result wait for ``timeout``.
    """
    results, pending, modes = {}, {}, {}
    for kind, plugin_id, path, convert, ttl, *rest in jobs:
        mode = rest[0] if rest else None
        modes[(kind, plugin_id)] = mode
        hit = cache.get(_fresh_key(kind, plugin_id, mode))
        if hit is not None:
            results[(kind, plugin_id)] = {**hit, "stale": False}
        else:
            pending[(kind, plugin_id)] = _submit(kind, plugin_id, path, convert, ttl, mode)

    started = time.monotonic()
    if pending and grace is not None:
        wait(pending.values(), timeout=grace)
        for (kind, plugin_id), future in list(pending.items()):
            if future.done():
                continue
            mode = modes[(kind, plugin_id)]
            last = cache.get(_last_key(kind, plugin_id, mode))
            if last is not None:
                stale = cache.get(_failed_key(kind, plugin_id, mode)) is not None
                results[(kind, plugin_id)] = {**last, "stale": stale, "refreshing": True}
                del pending[(kind, plugin_id)]
    if pending:
        wait(pending.values(), timeout=max(0, timeout - (time.monotonic() - started)))
    for (kind, plugin_id), future in pending.items():
        if future.done() and future.exception() is None:
            results[(kind, plugin_id)] = {**future.result(), "stale": False}
            continue
        if future.done():
            logger.warning("%s hook for %s failed: %s", kind, plugin_id, future.exception())
        else:
            logger.warning("%s hook for %s timed out", kind, plugin_id)
        last = cache.get(_last_key(kind, plugin_id, modes[(kind, plugin_id)]))
        if last is not None:
            results[(kind, plugin_id)] = {**last, "stale": True}
        if grace is not None and not future.done():
            results.setdefault((kind, plugin_id), {"value": None, "missing": True})["refreshing"] = True
    return results


def _visible(spec, mode):
    return any(mode in tile.modes for tile in spec.tiles)


def _offered(shortcuts, mode):
    return [sc for sc in shortcuts if mode in sc["modes"]]


def _status_job(spec, mode):
    return ("status", spec.id, spec.status, _status_value, _status_ttl,
            mode if _takes_mode(spec.status) else None)


def home_data(mode, timeout=TIMEOUT):
    """Status lines and shortcuts for the homepage in ``mode``.

    ``refreshing`` is true when some hook is still running in the background,
    so asking again in a few seconds will get newer results.
    """
    specs = plugins()
    jobs = [
        _status_job(s, mode) for s in specs if s.status and _visible(s, mode)
    ] + [
        ("shortcuts", s.id, s.shortcuts, _shortcuts_value, SHORTCUTS_TTL)
        for s in specs if s.shortcuts
    ]
    results = _gather(jobs, timeout, grace=REFRESH_GRACE)

    status = {}
    shortcuts = []
    refreshing = False
    for (kind, plugin_id), entry in results.items():
        refreshing = refreshing or entry.get("refreshing", False)
        if entry.get("missing"):
            continue
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
    return {"status": status, "shortcuts": shortcuts, "refreshing": refreshing}


def lodge_card(mode, timeout=STAY_TIMEOUT):
    """The lodge card from the first app with a card hook, or None.

    Guests get the header and readings only: alerts and the link are for
    the owners.
    """
    spec = next((s for s in plugins() if s.card), None)
    if spec is None:
        return None
    entry = _gather(
        [("card", spec.id, spec.card, _card_value, CARD_TTL)], timeout
    ).get(("card", spec.id))
    card = entry["value"] if entry else None
    if card is None:
        return None
    card = {**card, "stale": entry["stale"]}
    if mode == GUEST:
        card.update(alerts=[], url=None,
                    level=INFO if card["level"] == WARN else card["level"])
    return card


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
    cache.delete_many([_fresh_key("status", spec.id, m) for m in (None, *ALL_MODES)])
    cache.delete(_fresh_key("shortcuts", spec.id))
    return message


def forget_units():
    """Drop cached answers that show temperatures etc., after the hub's units change.

    The next request refreshes them; until then the last good answer is served.
    """
    keys = []
    for spec in plugins():
        keys += [_fresh_key("status", spec.id, m) for m in (None, *ALL_MODES)]
        keys += [_fresh_key("card", spec.id), _fresh_key("provide:stats", spec.id)]
    cache.delete_many(keys)


def run_action(plugin_id, row_id, action_id, mode, timeout=TIMEOUT):
    """Run a button from ``plugin_id``'s status as shown in ``mode``.

    ``row_id`` is "" for a tile-wide action. Raises ActionNotFound unless
    the app's current status (cached, as the homepage last saw it) offers
    that button on a tile visible in ``mode``; anything the app's handler
    raises propagates.
    """
    spec = next((s for s in plugins() if s.id == plugin_id), None)
    if spec is None or not (spec.status and spec.run_action) or not _visible(spec, mode):
        raise ActionNotFound(plugin_id)
    entry = _gather([_status_job(spec, mode)], timeout).get(("status", spec.id))
    status = (entry or {}).get("value") or {}
    if row_id:
        row = next((r for r in status.get("rows", ()) if r["id"] == row_id), None)
        actions = row["actions"] if row else ()
    else:
        actions = status.get("actions", ())
    if not any(a["id"] == action_id for a in actions):
        raise ActionNotFound(f"{plugin_id}/{row_id}/{action_id}")

    hook = _resolve(spec.run_action)
    if _takes_mode(spec.run_action):
        message = hook(row_id, action_id, mode=mode)
    else:
        message = hook(row_id, action_id)
    cache.delete_many([_fresh_key("status", spec.id, m) for m in (None, *ALL_MODES)])
    return message
