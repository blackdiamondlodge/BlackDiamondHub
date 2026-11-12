"""What the screensaver can show, from the apps that provide it (``hub.provides``).

Info-strip slots store qualified stat ids (``"<app>.<key>"``) and the cam
setting stores a qualified background id (``"<app>.<id>"``).
"""
from bdh_sdk.provides import SEASON

from hub import provides

# Stats the display works out itself.
LOCAL = {"days_until_lifts": "Days until lifts open"}


def owner(key):
    return key.split(".", 1)[0] if "." in key else None


def season_apps():
    """Labels of the apps that can bring a season forward."""
    return [provides.app_label(s) for s in provides.providers(SEASON)]


def stat_groups(current=()):
    """``[(group label, [(id, label)])]`` for the info-strip selects.

    Saved ids nobody offers any more stay selectable, marked unavailable, so
    saving the page never drops them.
    """
    groups = {}
    for qid, label, app in provides.stat_catalogue():
        groups.setdefault(app, []).append((qid, label))
    if season_apps():
        groups.setdefault("Screensaver", []).extend(LOCAL.items())
    out = list(groups.items())
    known = {qid for _, items in out for qid, _ in items} | {"none"}
    missing = sorted({c for c in current if c and c not in known})
    if missing:
        out.append(("Unavailable", [(c, f"{c} (unavailable)") for c in missing]))
    return out


def pick_background(items, chosen):
    """The chosen background, else the first."""
    chosen = (chosen or "").strip()
    found = next((b for b in items if b["id"] == chosen), None) if chosen else None
    return found or (items[0] if items else None)