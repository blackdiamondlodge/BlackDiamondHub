from functools import lru_cache
from importlib.metadata import packages_distributions, version

from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from hub.modes import plugins
from bdh_sdk.plugins import BOOL

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


def _lodge_sections():
    return [
        {"id": "apps", "label": "Apps", "icon": "fa-puzzle-piece", "url": reverse("hub_settings_apps"),
         "count": len(plugins())},
        {"id": "accounts", "label": "Accounts", "icon": "fa-user", "url": reverse("admin:auth_user_changelist")},
    ]


def _app_sections():
    return [
        {"id": spec.id, "label": _label(spec), "img": _icon(spec),
         "url": reverse("hub_settings_app", args=[spec.id])}
        for spec in plugins() if spec.settings
    ]


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
         "settings_url": reverse("hub_settings_app", args=[spec.id]) if spec.settings else ""}
        for spec in plugins()
    ]
    return _render(request, "hub_settings/apps.html", "apps", apps=apps)


def _spec(app_id):
    spec = next((s for s in plugins() if s.id == app_id and s.settings), None)
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
    return rows


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
                       rows=_rows(spec, saved, raw, errors), has_errors=True, status=400)

    return _render(request, "hub_settings/app.html", spec.id, spec=spec, label=_label(spec),
                   rows=_rows(spec, saved), just_saved=request.GET.get("saved") == "1")
