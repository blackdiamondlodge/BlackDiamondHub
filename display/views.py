import re
import secrets
from datetime import timedelta

from bdh_sdk.plugins import BOOL
from bdh_sdk.qr import qr_svg
from bdh_sdk.storage import app_state
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from hub import provides
from hub_settings import store
from hub_settings.views import _render, _save, staff_page

from . import catalog, options
from .library import photo_json, season_photos
from .models import SaverPhoto, UploadLink
from .photos import BadPhoto, add_photo
from .options import APP, SEASON_IDS, SEASONS, SLOTS, SOURCES, value
from .schedule import is_night, lodge_minute, parse_hhmm, window
from .season import by_date, lodge_today, parse_mmdd, resolve
from .stats import collect

SOURCE_LAYERS = {"stock": ["stock"], "photos": ["photos"], "cam": ["cam"], "mix": ["stock", "photos", "cam"]}


def season_signal():
    """Whether an app says winter has come early (None when no app can tell)."""
    from bdh_sdk.provides import SEASON

    if not provides.providers(SEASON):
        return None
    return any(h.get("season") == "winter" for h in provides.season_hints())


def current_season(today=None, signal=None):
    signal = season_signal() if signal is None else signal
    return resolve(today or lodge_today(), options.starts(), signal,
                   value("winter_on_lifts"), app_state(APP))


def _preview(request):
    """Unsaved settings-page values a staff preview may try out: source, cam, rotate, caption."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    out = {}
    if request.GET.get("source") in SOURCE_LAYERS:
        out["source"] = request.GET["source"]
    if "cam" in request.GET:
        out["cam"] = request.GET["cam"][:80]
    try:
        out["rotate"] = min(600, max(30, int(request.GET["rotate"])))
    except (KeyError, ValueError):
        pass
    if request.GET.get("caption") in ("0", "1"):
        out["caption"] = request.GET["caption"] == "1"
    return out


@require_GET
def saver_api(request):
    today = lodge_today()
    starts = options.starts()
    signal = season_signal()
    season = request.GET.get("season")
    if season not in SEASON_IDS:
        season = current_season(today, signal)
    preview = _preview(request)

    layers = SOURCE_LAYERS[preview.get("source") or value(f"source_{season}")]
    cam = None
    if "cam" in layers:
        found = catalog.pick_background(provides.backgrounds(), preview.get("cam", value("cam")))
        if found:
            cam = {"name": found["label"], "url": found["url"], "timestamp": found.get("timestamp"),
                   "refresh_seconds": found.get("refresh_seconds")}
    captions = preview.get("caption", value("photo_caption"))
    photos = season_photos(season, captions) if "photos" in layers else []
    layers = [layer for layer in layers if (layer != "cam" or cam) and (layer != "photos" or photos)]
    if not layers:
        layers = ["stock"]

    keys = [options.slot(season, n) for n in range(1, SLOTS + 1)]
    response = JsonResponse({
        "season": season,
        "label": dict(SEASONS)[season],
        "sources": layers,
        "rotate_seconds": preview.get("rotate", value("rotate_seconds")),
        "cam": cam,
        "photos": photos,
        "burn_in": value("burn_in"),
        "idle_minutes": value("idle_minutes"),
        "night": window(),
        "stats": collect(keys, today, starts, signal),
    })
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def schedule_api(request):
    """Night mode for Home Assistant: ``dark`` is true while the display should be off."""
    night = window()
    response = JsonResponse({
        "enabled": night is not None,
        "from": value("night_from") if night else None,
        "until": value("night_until") if night else None,
        "dark": bool(night) and is_night(lodge_minute(), night["from"], night["until"]),
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
            elif setting.key in ("night_from", "night_until"):
                minute = parse_hhmm(values[setting.key])
                values[setting.key] = f"{minute // 60:02d}:{minute % 60:02d}"
            if setting.key.startswith("slot_"):
                values[setting.key] = _slot_value(setting.key, values[setting.key])
        except ValueError as exc:
            errors[setting.key] = str(exc)
    return values, errors, raw


SLOT_ID = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)?$")


def _slot_value(key, posted):
    """A posted stat id; the site default is stored as empty so it follows the installed apps."""
    _, season, n = key.split("_")
    posted = (posted or "").strip()
    if not posted or posted == options.default_slot(season, int(n)):
        return ""
    if not SLOT_ID.match(posted):
        raise ValueError("Pick a stat from the list")
    return posted


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

    showing = current_season_safe()
    selected = request.GET.get("season") if request.GET.get("season") in SEASON_IDS else showing

    photos = list(SaverPhoto.objects.all())
    seasons = [{
        "id": sid, "label": label, "source": current[f"source_{sid}"],
        "photo_count": sum(1 for p in photos if p.enabled and p.in_season(sid)),
        "start": current[f"{sid}_start"], "start_key": f"{sid}_start",
        "start_error": errors.get(f"{sid}_start", ""),
        "slots": [{"n": n, "key": f"slot_{sid}_{n}", "value": options.slot(sid, n, current[f"slot_{sid}_{n}"])}
                  for n in range(1, SLOTS + 1)],
    } for sid, label in SEASONS]

    backgrounds = provides.backgrounds()
    cams = [{"slug": b["id"], "name": b["label"]} for b in backgrounds]
    chosen = catalog.pick_background(backgrounds, current["cam"])
    in_use = [slot["value"] for season in seasons for slot in season["slots"]]
    sources = SOURCES if backgrounds else [s for s in SOURCES if s[0] not in ("cam", "mix")]
    return _render(
        request, "display/settings.html", "display",
        v=current, errors=errors, seasons=seasons, selected=selected,
        showing=dict(SEASONS)[showing], sources=sources, slot_groups=catalog.stat_groups(in_use),
        cams=cams, cam_ids={c["slug"] for c in cams}, season_apps=catalog.season_apps(),
        default_cam=chosen["label"] if chosen else "",
        photos=[photo_json(p) for p in photos], season_choices=SEASONS,
        has_errors=bool(errors), just_saved=request.GET.get("saved") == "1", status=status,
    )


CLAIM_COOKIE = "display_upload"
CLAIMED_MINUTES = 30


def _seasons(raw):
    picked = [s for s in (raw or "").split(",") if s in SEASON_IDS]
    return [] if len(picked) == len(SEASON_IDS) else picked


def _add_files(request, link=None):
    seasons = _seasons(request.POST.get("seasons"))
    files = request.FILES.getlist("photo")
    if not files:
        return JsonResponse({"error": "No photo was sent."}, status=400)
    added = []
    for upload in files:
        try:
            added.append(photo_json(add_photo(upload, seasons, link)))
        except BadPhoto as exc:
            return JsonResponse({"error": str(exc), "photos": added}, status=400)
    return JsonResponse({"photos": added})


@staff_page
@require_POST
def link_create(request):
    UploadLink.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1)).delete()
    link = UploadLink.objects.create()
    url = request.build_absolute_uri(reverse("display_upload", args=[link.key]))
    return JsonResponse({"key": link.key, "url": url, "qr": qr_svg(url), "seconds": link.seconds_left()})


@staff_page
@require_GET
def photo_list(request):
    payload = {"photos": [photo_json(p) for p in SaverPhoto.objects.all()]}
    link = UploadLink.objects.filter(key=request.GET.get("link", "")).first()
    if link:
        payload["link"] = {"seconds": link.seconds_left(), "claimed": bool(link.claim),
                           "arrived": link.photos.count()}
    return JsonResponse(payload)


@staff_page
@require_POST
def photo_add(request):
    return _add_files(request)


@staff_page
@require_POST
def photo_update(request, photo_id):
    photo = get_object_or_404(SaverPhoto, pk=photo_id)
    if "enabled" in request.POST:
        photo.enabled = request.POST["enabled"] in ("1", "true", "on")
    if "seasons" in request.POST:
        photo.seasons = _seasons(request.POST["seasons"])
    photo.save()
    return JsonResponse(photo_json(photo))


@staff_page
@require_POST
def photo_delete(request, photo_id):
    get_object_or_404(SaverPhoto, pk=photo_id).delete()
    return JsonResponse({"ok": True})


def _link_for(request, key):
    """The upload link if this phone may use it, else (None, status, message)."""
    link = UploadLink.objects.filter(key=key).first()
    if not link:
        return None, 404, "This upload link isn't valid. Scan the code on the hub again."
    if not link.live():
        return None, 410, "This upload code has expired. Make a new one from the hub's Settings."
    if link.claim and not secrets.compare_digest(link.claim, request.COOKIES.get(CLAIM_COOKIE, "")):
        return None, 403, "This code is already in use on another phone. Make a new one from the hub."
    return link, 200, ""


def upload_page(request, key):
    link, status, message = _link_for(request, key)
    if not link:
        return render(request, "display/upload.html", {"message": message}, status=status)
    fresh = not link.claim
    if fresh:
        link.claim = secrets.token_urlsafe(24)
        link.expires_at = timezone.now() + timedelta(minutes=CLAIMED_MINUTES)
        link.save(update_fields=["claim", "expires_at"])
    response = render(request, "display/upload.html", {
        "link": link, "season_choices": SEASONS, "current": current_season_safe(),
        "post_url": reverse("display_upload_photo", args=[link.key]),
    })
    if fresh:
        response.set_cookie(CLAIM_COOKIE, link.claim, max_age=CLAIMED_MINUTES * 60, httponly=True,
                            samesite="Lax")
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def upload_photo(request, key):
    link, status, message = _link_for(request, key)
    if not link or not link.claim:
        return JsonResponse({"error": message or "Open the upload page first."}, status=status if not link else 403)
    return _add_files(request, link)


def current_season_safe():
    try:
        return current_season()
    except Exception:
        return by_date(lodge_today(), options.starts())
