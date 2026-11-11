"""Homepage mode resolution and tile lookup."""
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from .plugins import DASHBOARD, GUEST, OWNER, SECTIONS


def current_stay(request):
    """The stay in progress (see ``status.current_stay``), looked up once per request."""
    if not hasattr(request, "_hub_stay"):
        from . import status  # status imports this module

        request._hub_stay = status.current_stay()
    return request._hub_stay


def stay_active(request) -> bool:
    """Whether guests are currently staying, as reported by an app's stay hook."""
    return current_stay(request) is not None


def welcome(stay):
    """Template context for the guest welcome card."""
    checkout = stay["checkout"]
    return {"guest": stay["guest"], "checkout": _when(checkout) if checkout else ""}


def _when(t):
    # Shown in the stay's own timezone: the hub's TIME_ZONE is UTC.
    hour = t.strftime("%I").lstrip("0")
    minute = t.strftime(":%M") if t.minute else ""
    return f"{t:%A}, {t:%b} {t.day} at {hour}{minute} {t:%p}"


def resolve_mode(request) -> str:
    if request.user.is_authenticated:
        return OWNER
    if stay_active(request):
        return GUEST
    return DASHBOARD


def plugins():
    return getattr(settings, "HUB_PLUGINS", ())


SIZES = ("s", "m", "l")

# The home layout (tile order and size per section), saved from Settings.
LAYOUT_APP, LAYOUT_KEY = "hub", "home_layout"

# Tiles the hub draws itself rather than an app: the weather and the lodge card.
BUILTIN_TILES = (
    {"id": "hub:weather", "kind": "weather", "section": "mountain", "title": "Mountain conditions",
     "icon": "", "order": 0},
    {"id": "hub:lodge", "kind": "lodge", "section": "lodge", "title": "Lodge status",
     "icon": "", "order": 0},
)


def home_layout():
    """The saved layout: {section: [{"id": ..., "size": ...}, ...]}."""
    from bdh_sdk.settings import app_setting

    layout = app_setting(LAYOUT_APP, LAYOUT_KEY, {})
    return layout if isinstance(layout, dict) else {}


def _catalog(mode=None):
    """Every tile per section, in default order, optionally only those shown in ``mode``."""
    grouped = {key: [] for key in SECTIONS}
    for tile in BUILTIN_TILES:
        grouped[tile["section"]].append({**tile, "plugin": "", "subtitle": "", "url": ""})
    for spec in plugins():
        for tile in spec.tiles:
            if mode is not None and mode not in tile.modes:
                continue
            try:
                url = reverse(tile.url_name)
            except NoReverseMatch:
                continue
            grouped[tile.section].append({
                "id": f"{spec.id}:{tile.url_name}",
                "kind": "app",
                "plugin": spec.id,
                "title": tile.title,
                "subtitle": tile.subtitle,
                "url": url,
                "icon": tile.icon,
                "order": tile.order,
            })
    for items in grouped.values():
        items.sort(key=lambda t: (t["order"], t["title"]))
    return grouped


def arrange(items, saved):
    """Order and size ``items`` by the saved entries for their section.

    Saved tiles come first in their saved order; tiles the layout doesn't
    mention (e.g. a newly installed app) follow in default order. Without a
    saved size the first tile is large and the rest medium.
    """
    saved = [e for e in saved or () if isinstance(e, dict)]
    rank = {e.get("id"): i for i, e in enumerate(saved)}
    sizes = {e.get("id"): e.get("size") for e in saved}
    items = sorted(items, key=lambda t: rank.get(t["id"], len(rank)))
    for i, item in enumerate(items):
        size = sizes.get(item["id"])
        item["size"] = size if size in SIZES else ("l" if i == 0 else "m")
    return items


def tiles_for_mode(mode=None):
    """Return [(section_key, section_title, [tile dicts])], laid out as saved.

    With ``mode`` None every tile is included (the layout settings page).
    """
    grouped, layout = _catalog(mode), home_layout()
    sections = []
    for key, title in SECTIONS.items():
        items = arrange(grouped[key], layout.get(key))
        # The lodge card alone doesn't make a section: it's often empty.
        if any(t["kind"] != "lodge" for t in items):
            sections.append((key, title, items))
    return sections
