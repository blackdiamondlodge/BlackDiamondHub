import json
from functools import lru_cache
from importlib.metadata import packages_distributions, version

from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from hub.modes import LAYOUT_APP, LAYOUT_KEY, SIZES, plugins, tiles_for_mode
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
    return custom + [
        {"id": "home", "label": "Home layout", "icon": "fa-table-cells-large", "url": reverse("hub_settings_home")},
        {"id": "apps", "label": "Apps", "icon": "fa-puzzle-piece", "url": reverse("hub_settings_apps"),
         "count": len(plugins())},
        {"id": "accounts", "label": "Accounts", "icon": "fa-user", "url": reverse("admin:auth_user_changelist")},
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
    """Validate a posted layout against the tiles that exist; None if it's malformed."""
    try:
        posted = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(posted, dict):
        return None
    known = {key: {t["id"] for t in tiles} for key, _title, tiles in sections}
    layout = {}
    for key, ids in known.items():
        entries, seen = [], set()
        for entry in posted.get(key) or ():
            if not isinstance(entry, dict):
                return None
            tile_id, size = entry.get("id"), entry.get("size")
            if tile_id in ids and tile_id not in seen and size in SIZES:
                entries.append({"id": tile_id, "size": size})
                seen.add(tile_id)
        if entries:
            layout[key] = entries
    return layout


@staff_page
def home_layout(request):
    sections = tiles_for_mode(None)
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
                   customised=customised, just_saved=request.GET.get("saved") == "1")


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
