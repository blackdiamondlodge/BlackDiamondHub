"""Homepage mode resolution and tile lookup."""
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from .plugins import DASHBOARD, GUEST, OWNER, SECTIONS


def stay_active(request) -> bool:
    """Whether guests are currently staying. Wired up by the Stays app later."""
    return False


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
        if items:
            sections.append((key, title, items))
    return sections
