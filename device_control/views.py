"""
Views for the device_control app.

Provides:
  - device_control_view: renders the main page shell with tabs
  - device_control_states: AJAX endpoint returning current entity states as JSON
  - device_control_action: AJAX endpoint to toggle/control a device
"""

import json
import logging
import time

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .device_config import TABS, get_all_entity_ids, GEMSTONE_OVERRIDES
from .ha_client import (
    HAError,
    call_service,
    get_all_states,
    get_entity_states,
    get_static,
    ws_commands,
)
from . import gemstone_client

logger = logging.getLogger(__name__)

# Maps device type to the HA domain / service names
SERVICE_MAP = {
    "switch": {
        "on": ("switch", "turn_on"),
        "off": ("switch", "turn_off"),
        "toggle": ("switch", "toggle"),
    },
    "light": {
        "on": ("light", "turn_on"),
        "off": ("light", "turn_off"),
        "toggle": ("light", "toggle"),
    },
    "cover": {
        "open": ("cover", "open_cover"),
        "close": ("cover", "close_cover"),
        "stop": ("cover", "stop_cover"),
        "set_position": ("cover", "set_cover_position"),
    },
    "media_player": {
        "on": ("media_player", "turn_on"),
        "off": ("media_player", "turn_off"),
        "toggle": ("media_player", "toggle"),
    },
}


def device_control_view(request):
    """Render the device control page shell with tab definitions."""
    return render(request, "device_control/device_control.html", {"tabs": TABS})


def device_control_states(request):
    """
    AJAX endpoint: fetch current states for all configured entities.

    Returns JSON: { entity_id: { state, friendly_name, current_position? } }
    """
    all_ids = get_all_entity_ids()
    raw_states = get_entity_states(all_ids)

    result = {}
    for eid, data in raw_states.items():
        attrs = data.get("attributes", {})
        entry = {
            "state": data.get("state", "unknown"),
            "friendly_name": attrs.get("friendly_name", eid),
        }
        # Include position for covers
        pos = attrs.get("current_position")
        if pos is not None:
            entry["current_position"] = pos
        # Include brightness info for lights
        brightness = attrs.get("brightness")
        if brightness is not None:
            entry["brightness"] = brightness  # 0-255
        color_modes = attrs.get("supported_color_modes")
        if color_modes:
            entry["supported_color_modes"] = color_modes
        result[eid] = entry

    return JsonResponse(result)


@require_POST
def device_control_action(request):
    """
    AJAX endpoint: perform an action on a device.

    Expects JSON body: { entity_id, action, type }
      - entity_id: e.g. "switch.living_room_tv_socket_1"
      - action: e.g. "on", "off", "toggle", "open", "close", "stop"
      - type: e.g. "switch", "light", "cover", "media_player"
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    entity_id = body.get("entity_id", "")
    action = body.get("action", "")
    device_type = body.get("type", "")

    # Validate entity is in our config
    allowed = get_all_entity_ids()
    if entity_id not in allowed:
        return JsonResponse({"error": "Entity not allowed"}, status=403)

    # Look up the service call
    type_map = SERVICE_MAP.get(device_type)
    if not type_map:
        return JsonResponse({"error": f"Unknown device type: {device_type}"}, status=400)

    service_info = type_map.get(action)
    if not service_info:
        return JsonResponse({"error": f"Unknown action: {action}"}, status=400)

    domain, service = service_info

    # Pass brightness for light dimming
    extra_data = None
    if device_type == "light" and action == "on":
        brightness = body.get("brightness")
        if brightness is not None:
            extra_data = {"brightness": int(brightness)}
    elif device_type == "cover" and action == "set_position":
        position = body.get("position")
        if position is not None:
            extra_data = {"position": int(position)}

    success, error = call_service(domain, service, entity_id, extra_data=extra_data)

    if success:
        return JsonResponse({"ok": True, "entity_id": entity_id, "action": action})
    else:
        return JsonResponse({"ok": False, "error": error}, status=502)


# ──────────────────────────────────────────────
# Fireplace endpoints (Home Assistant / hass-napoleon)
# ──────────────────────────────────────────────
# The fireplace tab renders the napoleon-fireplace-card Lovelace card that
# ships with the hass-napoleon integration. These endpoints give the card a
# minimal ``hass`` object (states + registries) and proxy its service calls,
# restricted to Napoleon entities and the services the card actually uses.

FIREPLACE_CARD_PATH = "/napoleon_static/napoleon-fireplace-card.js"
_FIREPLACE_REGISTRY_TTL = 300  # seconds
_FIREPLACE_CARD_TTL = 600
_fireplace_cache = {}

FIREPLACE_SERVICES = {
    "switch": {"turn_on", "turn_off"},
    "light": {"turn_on", "turn_off"},
    "number": {"set_value"},
    "select": {"select_option"},
    "climate": {"set_hvac_mode", "set_preset_mode", "set_temperature"},
}
FIREPLACE_SERVICE_FIELDS = {
    "hvac_mode", "preset_mode", "temperature", "value", "brightness", "rgb_color", "option",
}


def _cached(key, ttl, loader):
    hit = _fireplace_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _fireplace_cache[key] = (now, value)
    return value


def _load_napoleon_registry():
    entities, devices, config = ws_commands(
        {"type": "config/entity_registry/list"},
        {"type": "config/device_registry/list"},
        {"type": "get_config"},
    )
    ents = {
        e["entity_id"]: {k: e.get(k) for k in ("entity_id", "device_id", "platform", "translation_key")}
        for e in entities
        if e.get("platform") == "napoleon" and not e.get("disabled_by")
    }
    device_ids = {e["device_id"] for e in ents.values() if e["device_id"]}
    devs = {
        d["id"]: {k: d.get(k) for k in ("id", "name", "name_by_user")}
        for d in devices
        if d["id"] in device_ids
    }
    unit = ((config or {}).get("unit_system") or {}).get("temperature", "°C")
    return {"entities": ents, "devices": devs, "config": {"unit_system": {"temperature": unit}}}


def _napoleon_registry():
    return _cached("registry", _FIREPLACE_REGISTRY_TTL, _load_napoleon_registry)


def device_control_fireplace_states(request):
    """AJAX endpoint: everything the fireplace card needs from ``hass``.

    Returns JSON: { entities, devices, config, states } limited to Napoleon
    entities, or 502 when Home Assistant is unreachable.
    """
    try:
        registry = _napoleon_registry()
        states = {
            s["entity_id"]: s
            for s in get_all_states()
            if s.get("entity_id") in registry["entities"]
        }
    except HAError as exc:
        logger.warning("Fireplace states fetch failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({**registry, "states": states})


@require_POST
def device_control_fireplace_action(request):
    """AJAX endpoint: proxy a card service call to Home Assistant.

    Expects JSON body: { domain, service, data: { entity_id, ...fields } }
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "Invalid body"}, status=400)

    domain = body.get("domain")
    service = body.get("service")
    data = body.get("data")
    if service not in FIREPLACE_SERVICES.get(domain, ()):
        return JsonResponse({"error": f"Service not allowed: {domain}.{service}"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Missing data"}, status=400)
    entity_id = data.get("entity_id")
    if not isinstance(entity_id, str) or entity_id.split(".", 1)[0] != domain:
        return JsonResponse({"error": "Invalid entity_id"}, status=400)
    extra = {k: v for k, v in data.items() if k != "entity_id"}
    if set(extra) - FIREPLACE_SERVICE_FIELDS:
        return JsonResponse({"error": "Unsupported service data"}, status=400)

    try:
        registry = _napoleon_registry()
    except HAError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    if entity_id not in registry["entities"]:
        return JsonResponse({"error": "Not a Napoleon entity"}, status=400)

    ok, err = call_service(domain, service, entity_id, extra)
    if not ok:
        return JsonResponse({"ok": False, "error": err}, status=502)
    return JsonResponse({"ok": True})


def device_control_fireplace_card(request):
    """Serve the integration's card JS same-origin (proxied from HA, cached)."""
    try:
        js = _cached("card", _FIREPLACE_CARD_TTL, lambda: get_static(FIREPLACE_CARD_PATH))
    except HAError as exc:
        logger.warning("Fireplace card fetch failed: %s", exc)
        return HttpResponse("// fireplace card unavailable", status=502, content_type="application/javascript")
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Cache-Control"] = "max-age=300"
    return resp


# ──────────────────────────────────────────────
# Gemstone Lights (cloud) endpoints
# ──────────────────────────────────────────────
# These bypass Home Assistant entirely and talk to the Gemstone Lights cloud
# through device_control.gemstone_client. The control surface is intentionally
# small: power on/off and selecting one of the user's saved patterns.

# Action -> validator for the supplied value. Anything not listed is rejected.
_GEMSTONE_ACTION_VALIDATORS = {
    "power": lambda v: isinstance(v, bool),
    "pattern": lambda v: isinstance(v, str) and bool(v),
}


def _apply_gemstone_overrides(state):
    """Apply optional name/room overrides from device_config to a state dict."""
    override = GEMSTONE_OVERRIDES.get(state.get("id"))
    if override:
        if override.get("name"):
            state["name"] = override["name"]
        if override.get("room"):
            state["room"] = override["room"]
    return state


def device_control_gemstone_states(request):
    """AJAX endpoint: current state of every Gemstone device + saved patterns.

    Returns JSON: { "configured": bool, "devices": [...], "patterns": [...] }
    """
    if not gemstone_client.is_configured():
        return JsonResponse({"configured": False, "devices": [], "patterns": []})

    try:
        data = gemstone_client.get_states()
    except gemstone_client.GemstoneError as exc:
        logger.warning("Gemstone states fetch failed: %s", exc)
        return JsonResponse({"configured": True, "error": str(exc)}, status=502)

    devices = [_apply_gemstone_overrides(d) for d in data.get("devices", [])]
    return JsonResponse(
        {
            "configured": True,
            "devices": devices,
            "patterns": data.get("patterns", []),
        }
    )


@require_POST
def device_control_gemstone_action(request):
    """AJAX endpoint: apply a control action to a Gemstone device.

    Expects JSON body: { device_id, action, value }
    Returns the refreshed device state on success.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    device_id = body.get("device_id", "")
    action = body.get("action", "")
    value = body.get("value")

    if not device_id:
        return JsonResponse({"error": "Missing device_id"}, status=400)

    validator = _GEMSTONE_ACTION_VALIDATORS.get(action)
    if validator is None:
        return JsonResponse({"error": f"Unknown action: {action}"}, status=400)
    if not validator(value):
        return JsonResponse(
            {"error": f"Invalid value for {action}: {value!r}"}, status=400
        )

    if not gemstone_client.is_configured():
        return JsonResponse({"error": "Gemstone not configured"}, status=503)

    try:
        state = gemstone_client.apply_action(device_id, action, value)
    except gemstone_client.GemstoneError as exc:
        logger.warning("Gemstone action %s failed: %s", action, exc)
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    return JsonResponse({"ok": True, "device": _apply_gemstone_overrides(state)})
