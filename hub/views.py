"""Homepage JSON API: status lines and quick-action shortcuts."""
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

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


SAMPLE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Test alert</title><style>
html{height:100%;background:linear-gradient(160deg,#1b2b4d,#5a6f9a)}body{margin:0;height:100%;color:#fff;
font:600 28px/1.3 system-ui,sans-serif;display:flex;align-items:center;justify-content:center;text-align:center}
</style></head><body><div>This is a test alert.<br><small style="font-weight:400;opacity:.7">
Apps show live video or other content here.</small></div></body></html>"""


@never_cache
@staff_member_required
def alert_test(request):
    """Pushes a sample alert to every screen. ``?embed=/path/`` shows that page instead."""
    from bdh_sdk.alerts import Alert, push

    try:
        alert = Alert(app="hub", key="hub:test", title="Test alert", body="Sent from the hub",
                      embed_url=request.GET.get("embed") or reverse("hub_alert_sample"),
                      ttl=int(request.GET.get("ttl", 30)))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    push(alert)
    return JsonResponse({"ok": True})


@require_GET
def alert_sample(request):
    return HttpResponse(SAMPLE_PAGE)