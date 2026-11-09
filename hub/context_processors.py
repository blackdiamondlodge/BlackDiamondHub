"""Template context shared by every page: navbar title and stay key."""
import hashlib
import logging

from django.urls import NoReverseMatch, reverse

from .modes import current_stay, plugins

log = logging.getLogger(__name__)


def stay_key(request):
    """``hub_stay_key``: an opaque id for the stay in progress, "" when there is none.

    Apps use it to reset per-stay browser data (e.g. the restaurants shortlist)
    when new guests arrive. It's a callable so the stay is only looked up on
    pages that render it.
    """
    def key():
        try:
            stay = current_stay(request)
        except Exception:
            log.exception("stay lookup failed")
            return ""
        if not stay:
            return ""
        arrival = stay["arrival"].isoformat() if stay["arrival"] else ""
        return hashlib.sha256(f"{stay['guest']}|{arrival}".encode()).hexdigest()[:12]

    return {"hub_stay_key": key}


def _tile_url(tile):
    try:
        return reverse(tile.url_name)
    except NoReverseMatch:
        return None


def nav_title(request):
    """Title of the plugin app that owns ``request.path``, or "" elsewhere.

    Uses the tile whose URL matches the page exactly, else the app's first
    tile. Templates can override it with ``{% block navbar_title %}``.
    """
    path = request.path
    best, best_len = None, -1
    for spec in plugins():
        if not spec.urls or not spec.tiles:
            continue
        prefix = "/" + spec.prefix
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = spec, len(prefix)
    if best is None:
        return {"hub_nav_title": ""}
    exact = next((t for t in best.tiles if _tile_url(t) == path), None)
    return {"hub_nav_title": (exact or best.tiles[0]).title}
