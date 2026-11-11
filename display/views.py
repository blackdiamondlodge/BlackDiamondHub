from bdh_sdk.plugins import BOOL
from bdh_sdk.storage import app_state
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from hub_settings import store
from hub_settings.views import _render, _save, staff_page

from . import options
from .options import APP, SEASON_IDS, SEASONS, SLOT_CHOICES, SLOTS, SOURCES, value
from .season import by_date, lodge_today, parse_mmdd, resolve
from .stats import collect, gather, lifts_open

SOURCE_LAYERS = {"stock": ["stock"], "cam": ["cam"], "mix": ["stock", "cam"]}


def _cams():
    try:
        from sunpeaks_webcams.views import feed

        cams, _wait = feed.get()
        return cams
    except Exception:
        return []


def pick_cam(cams, slug):
    """The chosen webcam, else one named Sunburst, else the first."""
    return (next((c for c in cams if c.get("slug") == slug), None) if slug else None) \
        or next((c for c in cams if "sunburst" in (c.get("camera_name") or "").lower()), None) \
        or (cams[0] if cams else None)


def current_season(data=None, today=None):
    data = gather() if data is None else data
    return resolve(today or lodge_today(), options.starts(), lifts_open(data),
                   value("winter_on_lifts"), app_state(APP))


@require_GET
def saver_api(request):
    data = gather()
    today = lodge_today()
    starts = options.starts()
    season = request.GET.get("season")
    if season not in SEASON_IDS:
        season = current_season(data, today)

    layers = SOURCE_LAYERS[value(f"source_{season}")]
    cam = None
    if "cam" in layers:
        found = pick_cam(_cams(), value("cam"))
        if found:
            cam = {"name": found.get("camera_name", ""), "url": found.get("image_url", ""),
                   "timestamp": found.get("timestamp")}
    if not cam:
        layers = ["stock"]

    keys = [value(f"slot_{season}_{n}") for n in range(1, SLOTS + 1)]
    response = JsonResponse({
        "season": season,
        "label": dict(SEASONS)[season],
        "sources": layers,
        "rotate_seconds": value("rotate_minutes") * 60,
        "cam": cam,
        "burn_in": value("burn_in"),
        "idle_minutes": value("idle_minutes"),
        "stats": collect(keys, data, today, starts),
    })
    response["Cache-Control"] = "no-store"
    return response


def _spec():
    from .plugin import spec

    return spec


def _form_values(post):
    values, errors, raw = {}, {}, {}
    for setting in options.SETTINGS:
        if setting.type == BOOL:
            raw[setting.key] = setting.key in post
        else:
            raw[setting.key] = post.get(setting.key, "")
        try:
            values[setting.key] = setting.parse(raw[setting.key])
            if setting.key.endswith("_start"):
                month, day = parse_mmdd(values[setting.key])
                values[setting.key] = f"{month:02d}-{day:02d}"
        except ValueError as exc:
            errors[setting.key] = str(exc)
    return values, errors, raw


def _current(spec, saved):
    return {s.key: saved.get(s.key, store.fallback(spec.id, s)) for s in spec.settings}


@staff_page
def settings_page(request):
    spec = _spec()
    saved = store.saved(spec.id)
    errors, status = {}, 200

    if request.method == "POST":
        values, errors, raw = _form_values(request.POST)
        if not errors:
            _save(request, spec, saved, values)
            tab = request.POST.get("tab")
            return redirect(f"{request.path}?saved=1" + (f"&season={tab}" if tab in SEASON_IDS else ""))
        current, status = {**_current(spec, saved), **raw}, 400
    else:
        current = _current(spec, saved)

    try:
        showing = current_season()
    except Exception:
        showing = by_date(lodge_today(), options.starts())
    selected = request.GET.get("season") if request.GET.get("season") in SEASON_IDS else showing

    seasons = [{
        "id": sid, "label": label, "source": current[f"source_{sid}"],
        "start": current[f"{sid}_start"], "start_key": f"{sid}_start",
        "start_error": errors.get(f"{sid}_start", ""),
        "slots": [{"n": n, "key": f"slot_{sid}_{n}", "value": current[f"slot_{sid}_{n}"]}
                  for n in range(1, SLOTS + 1)],
    } for sid, label in SEASONS]

    feed = _cams()
    cams = [{"slug": c.get("slug"), "name": c.get("camera_name")} for c in feed if c.get("slug")]
    chosen = pick_cam(feed, current["cam"])
    return _render(
        request, "display/settings.html", "display",
        v=current, errors=errors, seasons=seasons, selected=selected,
        showing=dict(SEASONS)[showing], sources=SOURCES, slot_choices=SLOT_CHOICES, cams=cams,
        default_cam=chosen.get("camera_name") if chosen else "",
        has_errors=bool(errors), just_saved=request.GET.get("saved") == "1", status=status,
    )
