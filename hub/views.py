"""Homepage JSON API: status lines and quick-action shortcuts."""
import logging

from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import status
from .modes import resolve_mode

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def home_status(request):
    mode = resolve_mode(request)
    data = status.home_data(mode)
    for sc in data["shortcuts"]:
        sc["url"] = reverse("hub_shortcut", args=[sc["plugin"], sc["id"]])
    return JsonResponse({"mode": mode, **data})


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
