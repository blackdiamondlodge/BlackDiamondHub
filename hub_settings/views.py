import json
from functools import lru_cache
from importlib.metadata import packages_distributions, version
from zoneinfo import available_timezones

import requests
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from hub.modes import (
    GROUP_KEY, LAYOUT_APP, LAYOUT_KEY, MAX_GROUPS, MAX_TITLE, SIZES, plugins, tiles_for_mode,
)
from bdh_sdk import units
from bdh_sdk.location import location as hub_location
from bdh_sdk.plugins import BOOL, MULTI

from . import store
from .models import AppSetting


def _is_staff(user):
    return user.is_active and user.is_staff


staff_page = user_passes_test(_is_staff)


def _label(spec):
    return spec.tiles[0].title if spec.tiles else spec.id.replace("_", " ").title()


def _icon(spec):
    return spec.tiles[0].icon if spec.tiles else ""


@lru_cache(maxsize=1)
def _distributions():
    return packages_distributions()


def _version(spec):
    module = spec.app.split(".")[0]
    for dist in _distributions().get(module, ()):
        try:
            return version(dist)
        except Exception:
            pass
    return ""


# Built-in apps whose settings have their own page instead of the generic form.
CUSTOM_PAGES = {"display": ("Display", "fa-tv", "display_settings")}


def _custom_url(app_id):
    page = CUSTOM_PAGES.get(app_id)
    if page and any(s.id == app_id for s in plugins()):
        return reverse(page[2])
    return ""


def _has_settings(spec):
    return bool(spec.settings or spec.settings_pages)


def _settings_url(spec):
    if not _has_settings(spec):
        return ""
    return _custom_url(spec.id) or reverse("hub_settings_app", args=[spec.id])


def _lodge_sections():
    custom = [
        {"id": app_id, "label": label, "icon": icon, "url": _custom_url(app_id)}
        for app_id, (label, icon, _name) in CUSTOM_PAGES.items() if _custom_url(app_id)
    ]
    return [
        {"id": "location", "label": "Location", "icon": "fa-location-dot", "url": reverse("hub_settings_location")},
    ] + custom + [
        {"id": "home", "label": "Home layout", "icon": "fa-table-cells-large", "url": reverse("hub_settings_home")},
        {"id": "apps", "label": "Apps", "icon": "fa-puzzle-piece", "url": reverse("hub_settings_apps"),
         "count": len(plugins())},
    ]


def _app_sections():
    return [
        {"id": spec.id, "label": _label(spec), "img": _icon(spec),
         "url": reverse("hub_settings_app", args=[spec.id])}
        for spec in plugins() if _has_settings(spec) and spec.id not in CUSTOM_PAGES
    ]


def _pages(spec):
    """Links to the app's own settings pages; ones that don't resolve are skipped."""
    pages = []
    for page in spec.settings_pages:
        try:
            url = reverse(page.url_name)
        except NoReverseMatch:
            continue
        pages.append({"title": page.title, "subtitle": page.subtitle, "icon": page.icon, "url": url})
    return pages


def _render(request, template, active, **context):
    context.update(lodge_sections=_lodge_sections(), app_sections=_app_sections(), active=active)
    return render(request, template, context, status=context.pop("status", 200))


@staff_page
def index(request):
    return redirect("hub_settings_apps")


@staff_page
def apps_overview(request):
    apps = [
        {"spec": spec, "label": _label(spec), "img": _icon(spec), "version": _version(spec),
         "settings_url": _settings_url(spec)}
        for spec in plugins()
    ]
    return _render(request, "hub_settings/apps.html", "apps", apps=apps)


def _parse_layout(raw, sections):
    """Validate a posted ``{"groups": [...]}`` layout; None if it's malformed.

    Every group needs a unique key and a title. Tiles that don't exist (or
    appear twice) are dropped.
    """
    try:
        posted = json.loads(raw)
    except ValueError:
        return None
    groups = posted.get("groups") if isinstance(posted, dict) else None
    if not isinstance(groups, list) or not 0 < len(groups) <= MAX_GROUPS:
        return None
    known = {t["id"] for _key, _title, tiles in sections for t in tiles}
    layout, keys, seen = [], set(), set()
    for group in groups:
        if not isinstance(group, dict):
            return None
        key, title, tiles = group.get("key"), group.get("title"), group.get("tiles")
        if not isinstance(key, str) or not GROUP_KEY.match(key) or key in keys:
            return None
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE:
            return None
        if not isinstance(tiles, list):
            return None
        entries = []
        for entry in tiles:
            if not isinstance(entry, dict):
                return None
            tile_id, size = entry.get("id"), entry.get("size")
            if tile_id in known and tile_id not in seen and size in SIZES:
                entries.append({"id": tile_id, "size": size})
                seen.add(tile_id)
        layout.append({"key": key, "title": title.strip(), "tiles": entries})
        keys.add(key)
    return {"groups": layout}


@staff_page
def home_layout(request):
    sections = tiles_for_mode(None, include_empty=True)
    if request.method == "POST":
        if request.POST.get("reset"):
            AppSetting.objects.filter(app_id=LAYOUT_APP, key=LAYOUT_KEY).delete()
            return redirect(f"{request.path}?saved=1")
        layout = _parse_layout(request.POST.get("layout", ""), sections)
        if layout is None:
            return _render(request, "hub_settings/home_layout.html", "home", sections=sections,
                           has_errors=True, status=400)
        AppSetting.objects.update_or_create(
            app_id=LAYOUT_APP, key=LAYOUT_KEY, defaults={"value": layout, "updated_by": request.user})
        return redirect(f"{request.path}?saved=1")
    customised = AppSetting.objects.filter(app_id=LAYOUT_APP, key=LAYOUT_KEY).exists()
    return _render(request, "hub_settings/home_layout.html", "home", sections=sections,
                   customised=customised, just_saved=request.GET.get("saved") == "1",
                   max_title=MAX_TITLE, max_groups=MAX_GROUPS)


def _spec(app_id):
    spec = next((s for s in plugins() if s.id == app_id and _has_settings(s)), None)
    if spec is None:
        raise Http404("No settings for that app")
    return spec


def _rows(spec, saved, posted=None, errors=None):
    rows = []
    for setting in spec.settings:
        default = store.fallback(spec.id, setting)
        if posted is not None and setting.key in posted:
            value = posted[setting.key]
        else:
            value = saved.get(setting.key, default)
        rows.append({
            "s": setting, "value": value, "default": default, "saved": setting.key in saved,
            "error": (errors or {}).get(setting.key, ""),
        })
        if setting.type == MULTI:
            rows[-1]["picks"] = _picks(setting, value)
    return rows


def _picks(setting, value):
    """Checkbox ``(value, label, checked)`` rows, keeping picked values no longer offered."""
    picked = [str(v) for v in value or ()]
    options = [(str(v), label) for v, label in setting.options]
    offered = {v for v, _label in options}
    return [(v, label, v in picked) for v, label in options] + [
        (v, v, True) for v in picked if v not in offered
    ]


def _save(request, spec, saved, values):
    for setting in spec.settings:
        key, value = setting.key, values[setting.key]
        if key in saved:
            if saved[key] != value:
                row = AppSetting.objects.get(app_id=spec.id, key=key)
                row.value, row.updated_by = value, request.user
                row.save()
        elif value != store.fallback(spec.id, setting):
            AppSetting.objects.create(app_id=spec.id, key=key, value=value, updated_by=request.user)


@staff_page
def app_settings(request, app_id):
    if _custom_url(app_id):
        return redirect(_custom_url(app_id))
    spec = _spec(app_id)
    saved = store.saved(spec.id)

    if request.method == "POST":
        reset = request.POST.get("reset")
        if reset:
            AppSetting.objects.filter(app_id=spec.id, key=reset).delete()
            return redirect(f"{request.path}?saved=1")
        values, errors, raw = {}, {}, {}
        for setting in spec.settings:
            if setting.type == BOOL:
                raw[setting.key] = setting.key in request.POST
            elif setting.type == MULTI:
                raw[setting.key] = request.POST.getlist(setting.key)
                if not raw[setting.key] and request.POST.get(f"{setting.key}__unset"):
                    # Never picked and still nothing ticked: saving other settings
                    # mustn't turn "not chosen yet" into "none".
                    raw[setting.key] = store.fallback(spec.id, setting)
                    values[setting.key] = raw[setting.key]
                    continue
            else:
                raw[setting.key] = request.POST.get(setting.key, "")
            try:
                values[setting.key] = setting.parse(raw[setting.key])
            except ValueError as exc:
                errors[setting.key] = str(exc)
        if not errors:
            _save(request, spec, saved, values)
            return redirect(f"{request.path}?saved=1")
        return _render(request, "hub_settings/app.html", spec.id, spec=spec, label=_label(spec),
                       rows=_rows(spec, saved, raw, errors), pages=_pages(spec), has_errors=True,
                       status=400)

    return _render(request, "hub_settings/app.html", spec.id, spec=spec, label=_label(spec),
                   rows=_rows(spec, saved), pages=_pages(spec),
                   just_saved=request.GET.get("saved") == "1")


LOCATION_APP, LOCATION_KEY = "hub", "location"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


@lru_cache(maxsize=1)
def _zones():
    return frozenset(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/")))


def _place(row):
    """An Open-Meteo geocoding result as the fields the Location page saves."""
    place = {
        "name": str(row.get("name") or ""),
        "region": str(row.get("admin1") or ""),
        "country": str(row.get("country") or ""),
        "country_code": str(row.get("country_code") or ""),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "timezone": row.get("timezone") if row.get("timezone") in available_timezones() else "",
    }
    place["label"] = ", ".join(p for p in (place["name"], place["region"], place["country"]) if p)
    return place


@staff_page
def location_search(request):
    """City search for the Location page. "Sun Peaks, Canada": the part after
    a comma narrows the results by region or country."""
    name, _sep, rest = request.GET.get("q", "").strip().partition(",")
    name, narrow = name.strip(), [w.strip().lower() for w in rest.split(",") if w.strip()]
    if len(name) < 2:
        return JsonResponse({"results": []})
    try:
        response = requests.get(GEOCODE_URL, timeout=8, params={
            "name": name, "count": 20 if narrow else 8, "language": "en", "format": "json"})
        response.raise_for_status()
        rows = response.json().get("results") or []
    except (requests.RequestException, ValueError, AttributeError):
        return JsonResponse({"error": "City search isn't available right now."}, status=502)
    places = [_place(r) for r in rows if isinstance(r, dict) and r.get("latitude") is not None
              and r.get("longitude") is not None]
    if narrow:
        def matches(p):
            haystack = " ".join((p["region"], p["country"], p["country_code"])).lower()
            return all(word in haystack for word in narrow)
        places = [p for p in places if matches(p)]
    return JsonResponse({"results": places[:8]})


def _number(raw, limit):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return round(value, 4) if -limit <= value <= limit else None


def _parse_location(post):
    """The posted Location form as the value to save, or ``(None, error)``."""
    lat, lon = _number(post.get("latitude"), 90), _number(post.get("longitude"), 180)
    name = post.get("name", "").strip()[:100]
    if not name or lat is None or lon is None:
        return None, "Pick a city from the search."
    geo_tz = post.get("geo_timezone", "").strip()
    geo_tz = geo_tz if geo_tz in available_timezones() else ""
    tz_auto = bool(post.get("tz_auto"))
    tz = geo_tz if tz_auto else post.get("timezone", "").strip()
    if tz_auto and not geo_tz:
        return None, "That city has no time zone; turn off automatic and pick one."
    if tz not in available_timezones():
        return None, "Pick a time zone."
    return {
        "name": name,
        "region": post.get("region", "").strip()[:100],
        "country": post.get("country", "").strip()[:100],
        "country_code": post.get("country_code", "").strip()[:2].upper(),
        "latitude": lat, "longitude": lon,
        "geo_timezone": geo_tz, "tz_auto": tz_auto, "timezone": tz,
    }, ""


UNIT_CHOICES = (("metric", "Metric", "°C, km, m"), ("imperial", "Imperial", "°F, miles, ft"))


def _save_units(request):
    """The hub-wide units; the same value as the home screen's °C/°F switch."""
    system = request.POST.get("units")
    if system in (units.METRIC, units.IMPERIAL) and system != units.system():
        AppSetting.objects.update_or_create(
            app_id="hub", key="units", defaults={"value": system, "updated_by": request.user})
        from hub import status
        status.forget_units()


@staff_page
def location_settings(request):
    saved = AppSetting.objects.filter(app_id=LOCATION_APP, key=LOCATION_KEY).first()
    error = ""
    if request.method == "POST":
        _save_units(request)
        value, error = _parse_location(request.POST)
        if value is not None:
            AppSetting.objects.update_or_create(
                app_id=LOCATION_APP, key=LOCATION_KEY, defaults={"value": value, "updated_by": request.user})
            from hub import status
            status.forget_units()
            return redirect(f"{request.path}?saved=1")
        current = {k: request.POST.get(k, "") for k in (
            "name", "region", "country", "country_code", "latitude", "longitude", "geo_timezone", "timezone")}
        current["tz_auto"] = bool(request.POST.get("tz_auto"))
    elif saved and isinstance(saved.value, dict):
        current = dict(saved.value)
    else:
        where = hub_location()
        current = {"name": where.name if where else "", "region": where.region if where else "",
                   "country": where.country if where else "", "country_code": "",
                   "latitude": where.latitude if where else "", "longitude": where.longitude if where else "",
                   "geo_timezone": "", "timezone": where.timezone if where else "", "tz_auto": True}
    current["label"] = ", ".join(str(current.get(k) or "") for k in ("name", "region", "country")
                                 if current.get(k))
    lat, lon = _number(current.get("latitude"), 90), _number(current.get("longitude"), 180)
    coords = f"{lat:.2f}, {lon:.2f}" if lat is not None and lon is not None else ""
    return _render(request, "hub_settings/location.html", "location", loc=current, error=error, coords=coords,
                   from_site=saved is None and request.method != "POST" and bool(current["timezone"]),
                   zones=sorted(_zones() | ({current["timezone"]} if current.get("timezone") else set())),
                   just_saved=request.GET.get("saved") == "1", status=400 if error else 200,
                   unit_choices=UNIT_CHOICES, hub_units=request.POST.get("units") or units.system())
