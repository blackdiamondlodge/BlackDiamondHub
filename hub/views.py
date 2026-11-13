"""Homepage JSON API: status lines and quick-action shortcuts."""
import hmac
import json
import logging
import os

from bdh_sdk import units
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from hub_settings.models import AppSetting

from . import status
from .modes import resolve_mode

logger = logging.getLogger(__name__)


# The homepage itself only waits this long for hooks with nothing cached yet;
# its first poll fills in the rest.
PAGE_TIMEOUT = 1.0


def home_data(mode, timeout=status.TIMEOUT):
    """``status.home_data`` plus each shortcut's URL."""
    data = status.home_data(mode, timeout=timeout)
    for sc in data["shortcuts"]:
        sc["url"] = reverse("hub_shortcut", args=[sc["plugin"], sc["id"]])
    for plugin_id, st in data["status"].items():
        if st.get("rows") or st.get("actions"):
            st["action_url"] = reverse("hub_action", args=[plugin_id])
    return data


@never_cache
@require_GET
def home_status(request):
    mode = resolve_mode(request)
    return JsonResponse({"mode": mode, "card": status.lodge_card(mode), **home_data(mode)})


@never_cache
@require_POST
def run_shortcut(request, plugin, shortcut):
    mode = resolve_mode(request)
    try:
        message = status.run_shortcut(plugin, shortcut, mode)
    except status.ShortcutNotFound:
        return JsonResponse({"ok": False, "error": "Shortcut not available"}, status=404)
    except Exception:
        logger.exception("Shortcut %s/%s failed", plugin, shortcut)
        return JsonResponse({"ok": False, "error": "That didn't work, please try again"}, status=502)
    return JsonResponse({"ok": True, "message": message or ""})


@never_cache
@require_POST
def run_action(request, plugin):
    """Runs a status button: form fields ``row`` ("" for tile-wide) and ``action``."""
    mode = resolve_mode(request)
    row, action = request.POST.get("row", ""), request.POST.get("action", "")
    try:
        message = status.run_action(plugin, row, action, mode)
    except status.ActionNotFound:
        return JsonResponse({"ok": False, "error": "That isn't available any more"}, status=404)
    except Exception:
        logger.exception("Action %s/%s/%s failed", plugin, row, action)
        return JsonResponse({"ok": False, "error": "That didn't work, please try again"}, status=502)
    return JsonResponse({"ok": True, "message": message or ""})


@never_cache
@require_POST
def set_units(request):
    """The title-bar °C/°F toggle: saves the hub-wide units every app follows.

    Anyone at the hub can flip it, guests included.
    """
    system = request.POST.get("units", "")
    if system not in (units.METRIC, units.IMPERIAL):
        return JsonResponse({"ok": False, "error": "units must be metric or imperial"}, status=400)
    if units.system() != system:
        user = request.user if request.user.is_authenticated else None
        AppSetting.objects.update_or_create(
            app_id="hub", key="units", defaults={"value": system, "updated_by": user})
        status.forget_units()
    return JsonResponse({"ok": True, "units": system})


SAMPLE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Test alert</title><style>
html{height:100%;background:linear-gradient(160deg,#1b2b4d,#5a6f9a)}body{margin:0;height:100%;color:#fff;
font:600 28px/1.3 system-ui,sans-serif;display:flex;align-items:center;justify-content:center;text-align:center}
</style></head><body><div>This is a test alert.<br><small style="font-weight:400;opacity:.7">
Apps show live video or other content here.</small></div></body></html>"""


@never_cache
@staff_member_required
def alert_test(request):
    """Pushes a sample alert to every screen. ``?embed=/path/`` shows that page instead; ``?sound=`` picks the chime."""
    from bdh_sdk.alerts import Alert, push

    try:
        alert = Alert(app="hub", key="hub:test", title="Test alert", body="Sent from the hub",
                      embed_url=request.GET.get("embed") or reverse("hub_alert_sample"),
                      ttl=int(request.GET.get("ttl", 30)), sound=request.GET.get("sound") or None)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    push(alert)
    return JsonResponse({"ok": True})


@require_GET
def alert_sample(request):
    return HttpResponse(SAMPLE_PAGE)


@require_GET
def og_image(request):
    """The site's link-preview card, for og:image (UniFi Connect thumbnails, chat apps)."""
    from .context_processors import og_image_path

    path = og_image_path()
    if not path:
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    return response



@csrf_exempt
@require_POST
def event_hook(request, source, topic):
    """Publish ``<source>/<topic>`` from a ``webhook`` event source (see hub/events.py)."""
    from bdh_sdk import events

    conf = settings.HUB_EVENT_SOURCES.get(source)
    if not conf or conf["type"] != "webhook":
        raise Http404
    secret = os.environ.get(conf["secret_env"], "")
    given = request.headers.get("X-Hub-Secret", "")
    if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        data = json.loads(request.body) if request.body else None
    except ValueError:
        return JsonResponse({"error": "body must be JSON"}, status=400)
    try:
        events.publish(f"{source}/{topic}", data)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})
