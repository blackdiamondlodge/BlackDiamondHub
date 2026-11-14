"""Remote control of hub screens, for development.

Off unless ``HUB_REMOTE_TOKEN`` is set; leave it unset in production. When it
is set, every hub page opens ``ws/hub/remote/`` (``hub/remote.js``) and
``/hub/api/remote/`` drives them:

``GET`` (header ``X-Hub-Token``)
    The connected screens: ``{"screens": [{"id", "ip", "path", "title",
    "size", "ua", "since"}]}``.

``POST`` (header ``X-Hub-Token``) ``{"target": ip or id, "cmd": ..., "args": {...}, "timeout": s}``
    Runs a command on that screen (the newest connection from that IP) and
    returns ``{"ok": true, "value": ...}`` or ``{"ok": false, "error": ...}``.
    With one screen connected ``target`` can be left out. The commands
    (``tap``, ``swipe``, ``key``, ``state``, ``query``, ``measure``, ``logs``,
    ``navigate``, ``reload``, ``back``, ``eval``) are documented in
    ``hub/static/hub/remote.js``.

Commands and screens live in this process, which is fine for the single
Daphne process the hub runs as.
"""
import asyncio
import hmac
import itertools
import json
import os
import time

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

DEFAULT_TIMEOUT = 15
MAX_TIMEOUT = 120

_screens = {}  # channel name -> screen info
_pending = {}  # command id -> future
_ids = itertools.count(1)


def token():
    return os.environ.get("HUB_REMOTE_TOKEN", "").strip()


def enabled():
    return bool(token())


class RemoteConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        if not enabled() or self.channel_layer is None:
            await self.close()
            return
        client = self.scope.get("client") or ("?", 0)
        _screens[self.channel_name] = {
            "id": f"s{next(_ids)}", "ip": client[0], "path": "", "title": "",
            "size": None, "ua": "", "since": time.time(),
        }
        await self.accept()

    async def disconnect(self, code):
        _screens.pop(self.channel_name, None)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "hello":
            info = _screens.get(self.channel_name)
            if info is not None:
                info.update({k: content.get(k) for k in ("path", "title", "size", "ua")})
        elif kind == "result":
            future = _pending.get(content.get("id"))
            if future is not None and not future.done():
                future.set_result({k: content[k] for k in ("ok", "value", "error") if k in content})

    async def hub_remote(self, event):
        await self.send_json(event["command"])


def _listing():
    return sorted(({**info, "since": round(info["since"])} for info in _screens.values()),
                  key=lambda s: s["since"])


def _pick(target):
    """Channel name for ``target`` (screen id or IP; newest connection wins)."""
    entries = sorted(_screens.items(), key=lambda kv: kv[1]["since"], reverse=True)
    if not target:
        ips = {info["ip"] for _, info in entries}
        return entries[0][0] if len(ips) == 1 else None
    for name, info in entries:
        if target in (info["id"], info["ip"]):
            return name
    return None


@csrf_exempt
@never_cache
async def api(request):
    if not enabled():
        raise Http404
    if not hmac.compare_digest(request.headers.get("X-Hub-Token", ""), token()):
        return JsonResponse({"ok": False, "error": "bad token"}, status=403)
    if request.method == "GET":
        return JsonResponse({"screens": _listing()})
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "GET or POST"}, status=405)
    try:
        body = json.loads(request.body or b"{}")
        cmd = str(body["cmd"])
        timeout = min(float(body.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "body must be JSON with a cmd"}, status=400)
    channel = _pick(body.get("target"))
    if channel is None:
        return JsonResponse({"ok": False, "error": "no such screen", "screens": _listing()}, status=404)

    from channels.layers import get_channel_layer

    command_id = next(_ids)
    future = asyncio.get_running_loop().create_future()
    _pending[command_id] = future
    try:
        await get_channel_layer().send(channel, {"type": "hub.remote", "command": {
            "type": "cmd", "id": command_id, "cmd": cmd, "args": body.get("args") or {}}})
        result = await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        return JsonResponse({"ok": False, "error": f"no reply in {timeout:g}s"}, status=504)
    finally:
        _pending.pop(command_id, None)
    return JsonResponse(result)
