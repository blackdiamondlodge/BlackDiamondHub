"""Homepage JSON API: status lines and quick-action shortcuts."""
import logging

from django.http import JsonResponse
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
