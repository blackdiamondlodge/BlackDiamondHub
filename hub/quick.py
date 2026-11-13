"""The quick-actions bar's preferences, set on Settings › Quick actions.

Saved as one value::

    {"grouped": bool, "pinned": ["plugin/shortcut", ...],
     "order": ["plugin", ...], "modes": {"plugin": ["guest", ...]}}

``order`` ranks apps' groups on the bar (apps it doesn't mention follow,
alphabetically). ``modes`` narrows the modes an app's buttons appear in; an
app it doesn't mention keeps each shortcut's own modes. Pinned buttons stay
one tap when the bar is too busy for every button.
"""
from bdh_sdk.settings import app_setting

from .plugins import DASHBOARD, GUEST, OWNER

QUICK_APP, QUICK_KEY = "hub", "quick"
MODES = ((GUEST, "Guest"), (DASHBOARD, "Dashboard"), (OWNER, "Owner"))
_MODE_IDS = {m for m, _label in MODES}


def app_label(spec):
    """An app's display name: its first tile's title, else its id."""
    return spec.tiles[0].title if spec.tiles else spec.id.replace("_", " ").title()


def clean(raw):
    """``raw`` (as saved, or anything else) as a complete, valid preferences dict."""
    raw = raw if isinstance(raw, dict) else {}
    pinned = raw.get("pinned")
    order = raw.get("order")
    modes = raw.get("modes")
    return {
        "grouped": raw.get("grouped", True) is not False,
        "pinned": [p for p in pinned if isinstance(p, str)] if isinstance(pinned, list) else [],
        "order": [p for p in order if isinstance(p, str)] if isinstance(order, list) else [],
        "modes": {
            app: [m for m in allowed if m in _MODE_IDS]
            for app, allowed in (modes.items() if isinstance(modes, dict) else ())
            if isinstance(app, str) and isinstance(allowed, list)
        },
    }


def prefs():
    return clean(app_setting(QUICK_APP, QUICK_KEY, {}))


def app_allows(prefs, plugin_id, mode):
    allowed = prefs["modes"].get(plugin_id)
    return allowed is None or mode in allowed


def app_rank(prefs, labels):
    """``plugin_id -> sort key``: saved order first, then by name."""
    rank = {app: i for i, app in enumerate(prefs["order"])}
    return lambda plugin_id: (rank.get(plugin_id, len(rank)), labels.get(plugin_id, plugin_id).lower())
