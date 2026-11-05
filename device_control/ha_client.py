"""
Home Assistant REST API client for device_control app.

Provides functions to fetch entity states and call services
(switch on/off, cover open/close, light on/off, etc.).
"""

import json
import logging
import requests
from urllib.parse import urljoin
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10  # seconds


def _headers():
    """Authorization headers for Home Assistant API."""
    return {
        "Authorization": f"Bearer {settings.HOMEASSISTANT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _base_url():
    """Home Assistant base URL."""
    return settings.HOMEASSISTANT_URL


def get_entity_state(entity_id):
    """
    Fetch the current state of a single entity.

    Returns dict with 'entity_id', 'state', and 'attributes',
    or None on failure.
    """
    url = urljoin(_base_url(), f"/api/states/{entity_id}")
    try:
        resp = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("HA returned %s for %s", resp.status_code, entity_id)
    except requests.RequestException as exc:
        logger.error("Failed to get state for %s: %s", entity_id, exc)
    return None


def get_entity_states(entity_ids):
    """
    Fetch states for multiple entities.

    Returns a dict mapping entity_id -> state dict.
    Fetches all states in a single call and filters.
    """
    url = urljoin(_base_url(), "/api/states")
    try:
        resp = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if resp.status_code == 200:
            all_states = resp.json()
            wanted = set(entity_ids)
            return {
                s["entity_id"]: s
                for s in all_states
                if s["entity_id"] in wanted
            }
        logger.warning("HA returned %s fetching all states", resp.status_code)
    except requests.RequestException as exc:
        logger.error("Failed to fetch states: %s", exc)
    return {}


def get_history(entity_ids, start, end=None):
    """
    Fetch state history for the given entities between ``start`` and ``end``
    (timezone-aware datetimes).

    Returns a dict mapping entity_id -> list of (iso_timestamp, state) tuples,
    oldest first. Returns {} on failure.
    """
    url = urljoin(_base_url(), f"/api/history/period/{start.isoformat()}")
    params = {
        "filter_entity_id": ",".join(entity_ids),
        "minimal_response": "",
        "no_attributes": "",
    }
    if end is not None:
        params["end_time"] = end.isoformat()
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.warning("HA returned %s fetching history", resp.status_code)
            return {}
        result = {}
        for series in resp.json():
            if not series:
                continue
            # With minimal_response only the first item carries entity_id.
            eid = series[0].get("entity_id")
            result[eid] = [
                (item.get("last_changed") or item.get("last_updated"), item.get("state"))
                for item in series
            ]
        return result
    except (requests.RequestException, ValueError) as exc:
        logger.error("Failed to fetch history: %s", exc)
    return {}


def call_service(domain, service, entity_id, extra_data=None):
    """
    Call a Home Assistant service.

    Args:
        domain: e.g. 'switch', 'light', 'cover'
        service: e.g. 'turn_on', 'turn_off', 'toggle', 'open_cover', 'close_cover'
        entity_id: The entity to target
        extra_data: Optional dict of additional service data

    Returns:
        (success: bool, error: str or None)
    """
    url = urljoin(_base_url(), f"/api/services/{domain}/{service}")
    payload = {"entity_id": entity_id}
    if extra_data:
        payload.update(extra_data)

    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=TIMEOUT)
        if resp.status_code == 200:
            return True, None
        msg = f"HA returned {resp.status_code}: {resp.text[:200]}"
        logger.warning(msg)
        return False, msg
    except requests.RequestException as exc:
        msg = f"Request failed: {exc}"
        logger.error(msg)
        return False, msg


class HAError(Exception):
    """Raised when a Home Assistant WebSocket command fails."""


def ws_commands(*messages):
    """
    Run Home Assistant WebSocket commands over one connection.

    Each message is a dict like {"type": "config/device_registry/list"}.
    Returns the list of results in order. Used for data REST doesn't expose
    (entity / device registries). Raises HAError on any failure.
    """
    import websocket

    base = _base_url().rstrip("/")
    url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/websocket"
    try:
        ws = websocket.create_connection(url, timeout=TIMEOUT)
    except (OSError, websocket.WebSocketException) as exc:
        raise HAError(f"connect failed: {exc}") from exc
    try:
        ws.recv()  # auth_required
        ws.send(json.dumps({"type": "auth", "access_token": settings.HOMEASSISTANT_ACCESS_TOKEN}))
        if json.loads(ws.recv()).get("type") != "auth_ok":
            raise HAError("auth failed")
        results = []
        for i, message in enumerate(messages, start=1):
            ws.send(json.dumps({**message, "id": i}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == i:
                    break
            if not msg.get("success"):
                raise HAError(f"{message.get('type')} failed: {msg.get('error')}")
            results.append(msg.get("result"))
        return results
    except (OSError, ValueError, websocket.WebSocketException) as exc:
        raise HAError(f"websocket command failed: {exc}") from exc
    finally:
        ws.close()

def get_all_states():
    """Fetch every entity state as a list. Raises HAError on failure."""
    url = urljoin(_base_url(), "/api/states")
    try:
        resp = requests.get(url, headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise HAError(f"states fetch failed: {exc}") from exc
    if resp.status_code != 200:
        raise HAError(f"HA returned {resp.status_code} fetching states")
    return resp.json()


def get_static(path):
    """Fetch a static file served by HA (e.g. an integration's card JS)."""
    url = urljoin(_base_url(), path)
    try:
        resp = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise HAError(f"fetch {path} failed: {exc}") from exc
    if resp.status_code != 200:
        raise HAError(f"HA returned {resp.status_code} for {path}")
    return resp.content