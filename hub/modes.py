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


def tiles_for_mode(mode):
    """Return [(section_key, section_title, [tile dicts])] for the mode."""
    grouped = {key: [] for key in SECTIONS}
    for spec in plugins():
        for tile in spec.tiles:
            if mode not in tile.modes:
                continue
            try:
                url = reverse(tile.url_name)
            except NoReverseMatch:
                continue
            grouped[tile.section].append({
                "plugin": spec.id,
                "title": tile.title,
                "subtitle": tile.subtitle,
                "url": url,
                "icon": tile.icon,
                "order": tile.order,
            })
    sections = []
    for key, title in SECTIONS.items():
        items = sorted(grouped[key], key=lambda t: (t["order"], t["title"]))
        # Sections are two tiles tall. With an odd count the first tile (by
        # order) spans both rows so the grid has no hole; the rest are half.
        for i, item in enumerate(items):
            item["size"] = "lg" if i == 0 and len(items) % 2 else "half"
        if items:
            sections.append((key, title, items))
    return sections
