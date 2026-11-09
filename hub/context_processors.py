"""Navbar context: the current app's title, shown centred in the top bar."""
from django.urls import NoReverseMatch, reverse

from .modes import plugins


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
