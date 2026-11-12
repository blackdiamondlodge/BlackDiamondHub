"""What the screensaver can show, from the apps that provide it (``hub.provides``).

Info-strip slots store qualified stat ids (``"<app>.<key>"``); the cam setting
stores a qualified background id. Older saved values use bare keys and cam
slugs, normalized here when read.

Until an app provides a capability itself, the display's own adapters for
Sun Peaks' snow report, lift status and webcams stand in for it, per app.
"""
from bdh_sdk.provides import BACKGROUNDS, SEASON

from hub import provides
from hub.modes import plugins

# Qualified id -> (display adapter key, label), used while that app doesn't provide stats.
LEGACY = {
    "snow_report.temp_top": ("temp_top", "Temp up top"),
    "snow_report.temp_mid": ("temp_mid", "Temp mid-mountain"),
    "snow_report.temp_village": ("temp_village", "Temp at the lodge"),
    "snow_report.snow_48h": ("new_snow", "New snow, 48h"),
    "snow_report.base": ("base", "Base depth"),
    "snow_report.wind_top": ("wind_top", "Wind up top"),
    "snow_report.sunrise": ("sunrise", "Sunrise"),
    "snow_report.sunset": ("sunset", "Sunset"),
    "lift_status.runs_open": ("runs_open", "Runs open"),
    "lift_status.lifts_open": ("lifts_open", "Lifts open"),
    "lift_status.groomed": ("groomed", "Runs groomed"),
    "weather.sunrise": ("sunrise", "Sunrise"),
    "weather.sunset": ("sunset", "Sunset"),
}
# Bare keys saved before stats were qualified.
ALIASES = {
    "temp_top": "snow_report.temp_top",
    "temp_mid": "snow_report.temp_mid",
    "temp_village": "snow_report.temp_village",
    "new_snow": "snow_report.snow_48h",
    "base": "snow_report.base",
    "wind_top": "snow_report.wind_top",
    "runs_open": "lift_status.runs_open",
    "lifts_open": "lift_status.lifts_open",
    "groomed": "lift_status.groomed",
}
SUN_APPS = ("snow_report", "weather")  # who answers a bare "sunrise"/"sunset", first installed wins
# Stats the display works out itself.
LOCAL = {"days_until_lifts": "Days until lifts open"}
LEGACY_CAMS = "sunpeaks_webcams"


def installed():
    return {s.id: s for s in plugins()}


def normalize(key):
    """A slot value as a qualified stat id (or ``"none"``, a local key, or ``""``)."""
    key = (key or "").strip()
    if key in ("sunrise", "sunset"):
        ids = installed()
        return f"{next((a for a in SUN_APPS if a in ids), SUN_APPS[0])}.{key}"
    return ALIASES.get(key, key)


def owner(key):
    return key.split(".", 1)[0] if "." in key else None


def season_apps():
    """Labels of apps that can bring a season forward (the legacy lift adapter counts)."""
    specs = provides.providers(SEASON)
    if specs:
        return [provides.app_label(s) for s in specs]
    lifts = installed().get("lift_status")
    return [provides.app_label(lifts)] if lifts else []


def stat_groups(current=()):
    """``[(group label, [(id, label)])]`` for the info-strip selects.

    Saved ids nobody offers any more stay selectable, marked unavailable, so
    saving the page never drops them.
    """
    groups = {}
    owners = provides.stat_owners()
    for qid, label, app in provides.stat_catalogue():
        groups.setdefault(app, []).append((qid, label))
    specs = installed()
    for qid, (_key, label) in LEGACY.items():
        app = owner(qid)
        if app in specs and app not in owners:
            groups.setdefault(provides.app_label(specs[app]), []).append((qid, label))
    if season_apps():
        groups.setdefault("Screensaver", []).extend(LOCAL.items())
    out = list(groups.items())
    known = {qid for _, items in out for qid, _ in items} | {"none"}
    missing = sorted({c for c in current if c and c not in known})
    if missing:
        out.append(("Unavailable", [(c, f"{c} (unavailable)") for c in missing]))
    return out


def _legacy_cams(cams):
    """The display's own webcam list as backgrounds, Sunburst first."""
    cams = sorted((c for c in cams if c.get("slug") and c.get("image_url")),
                  key=lambda c: "sunburst" not in (c.get("camera_name") or "").lower())
    return [{"id": f"{LEGACY_CAMS}.{c['slug']}", "label": c.get("camera_name") or c["slug"],
             "url": c["image_url"], "refresh_seconds": 60, "live": True, "app": "Webcams"}
            for c in cams]


def backgrounds(legacy_cams):
    """Provided backgrounds, else the legacy webcams from ``legacy_cams()``."""
    if provides.providers(BACKGROUNDS):
        return provides.backgrounds()
    return _legacy_cams(legacy_cams())


def background_id(value):
    """A saved cam value as a qualified background id; old values are webcam slugs."""
    value = (value or "").strip()
    return value if not value or "." in value else f"{LEGACY_CAMS}.{value}"


def pick_background(items, chosen):
    """The chosen background, else the first."""
    chosen = background_id(chosen)
    found = next((b for b in items if b["id"] == chosen), None) if chosen else None
    return found or (items[0] if items else None)
