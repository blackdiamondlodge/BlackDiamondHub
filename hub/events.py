"""Event sources: the hub end of ``bdh_sdk.events``.

Each ``[events.sources.<name>]`` table in ``site.toml`` is a source that
publishes topics starting with ``<name>/``:

``type = "home_assistant"``
    One websocket to Home Assistant (``url_env`` / ``token_env`` name the
    environment variables, default ``HOMEASSISTANT_URL`` /
    ``HOMEASSISTANT_ACCESS_TOKEN``). Publishes ``<name>/state/<entity_id>``
    with ``{"entity_id", "old", "new", "attributes"}``. It asks Home
    Assistant only for the entities apps subscribed to; a wildcard pattern
    that could match any entity switches it to every state change.
    Reconnects on its own; changes while disconnected are lost.

``type = "webhook"``
    ``POST /hub/api/events/hook/<name>/<topic...>`` with header
    ``X-Hub-Secret: <value of secret_env>`` publishes ``<name>/<topic...>``
    with the JSON body (or ``None``) as data. Disabled while the secret is unset.
"""
import json
import logging
import os
import sys
import threading
import time

from bdh_sdk import events

log = logging.getLogger(__name__)

TYPES = ("home_assistant", "webhook")
_PROBE = "zz_probe.zz_probe"

_sources = {}


def should_start(argv=None):
    """Run sources only in the server process (Daphne, or runserver's reloaded child)."""
    if os.environ.get("HUB_EVENTS", "").lower() in ("0", "false", "off", "no"):
        return False
    argv = sys.argv if argv is None else argv
    prog = os.path.basename(argv[0]) if argv else ""
    if "daphne" in prog:
        return True
    if len(argv) > 1 and prog in ("manage.py", "django-admin", "__main__.py") and argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true" or "--noreload" in argv
    return False


def start(sources):
    """Start the ``home_assistant`` sources from the site's config."""
    for name, conf in sources.items():
        if conf["type"] != "home_assistant" or name in _sources:
            continue
        url = os.environ.get(conf.get("url_env", "HOMEASSISTANT_URL"), "")
        token = os.environ.get(conf.get("token_env", "HOMEASSISTANT_ACCESS_TOKEN"), "")
        if not url or not token:
            log.warning("event source %s: no Home Assistant url/token; not started", name)
            continue
        source = HomeAssistantSource(name, url, token)
        _sources[name] = source
        source.start()


def wanted_entities(name, patterns):
    """Entity ids source ``name`` must watch, or ``None`` for every entity."""
    entities = set()
    for pattern in patterns:
        parts = pattern.split("/")
        if len(parts) == 3 and parts[:2] == [name, "state"] and "+" not in parts[2] and "#" not in parts[2]:
            entities.add(parts[2])
        elif events.matches(pattern, f"{name}/state/{_PROBE}"):
            return None
    return entities


def state_event(entity_id, old, new):
    return {
        "entity_id": entity_id,
        "old": (old or {}).get("state"),
        "new": (new or {}).get("state"),
        "attributes": (new or {}).get("attributes", {}),
    }


class HomeAssistantSource:
    RETRY_MIN, RETRY_MAX = 5, 60
    IDLE = 30  # seconds without traffic before a ping

    def __init__(self, name, url, token):
        self.name = name
        self.url = url.rstrip("/").replace("http", "ws", 1) + "/api/websocket"
        self.token = token
        self.entities = set()
        self._ws = None
        self._lock = threading.Lock()

    def start(self):
        events.add_listener(self._patterns_changed)
        threading.Thread(target=self._run, name=f"events-{self.name}", daemon=True).start()

    def _patterns_changed(self, patterns):
        wanted = wanted_entities(self.name, patterns)
        with self._lock:
            if wanted == self.entities:
                return
            self.entities = wanted
            ws = self._ws
        if ws is not None:
            ws.close()  # the reader reconnects with the new subscription

    def _run(self):
        time.sleep(2)  # let apps subscribe before the first connect
        delay = self.RETRY_MIN
        while True:
            try:
                self._session()
                delay = self.RETRY_MIN
            except Exception as exc:
                log.warning("event source %s: %s; retrying in %ss", self.name, exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, self.RETRY_MAX)

    def _session(self):
        import websocket

        with self._lock:
            entities = self.entities
        if entities == set():
            time.sleep(self.IDLE)  # nobody subscribed; check again later
            return
        ws = websocket.create_connection(self.url, timeout=10)
        try:
            if json.loads(ws.recv()).get("type") != "auth_required":
                raise ConnectionError("unexpected greeting")
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            if json.loads(ws.recv()).get("type") != "auth_ok":
                raise ConnectionError("authentication failed")
            if entities is None:
                ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
            else:
                ws.send(json.dumps({"id": 1, "type": "subscribe_trigger", "trigger": {
                    "platform": "state", "entity_id": sorted(entities)}}))
            with self._lock:
                if entities != self.entities:
                    return  # changed while connecting
                self._ws = ws
            log.info("event source %s: connected, watching %s", self.name,
                     "every entity" if entities is None else ", ".join(sorted(entities)))
            self._read(ws)
        finally:
            with self._lock:
                if self._ws is ws:
                    self._ws = None
            ws.close()

    def _read(self, ws):
        import websocket

        ws.settimeout(self.IDLE)
        next_id, waiting = 2, False
        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                if waiting:
                    raise ConnectionError("no pong")
                ws.send(json.dumps({"id": next_id, "type": "ping"}))
                next_id, waiting = next_id + 1, True
                continue
            if not raw:
                if not ws.connected:
                    return
                continue
            waiting = False
            self._handle(json.loads(raw))

    def _handle(self, msg):
        if msg.get("type") == "result" and not msg.get("success", True):
            raise ConnectionError(f"subscribe failed: {msg.get('error')}")
        if msg.get("type") != "event":
            return
        event = msg.get("event", {})
        if "variables" in event:  # subscribe_trigger
            trigger = event["variables"].get("trigger", {})
            entity_id, old, new = trigger.get("entity_id"), trigger.get("from_state"), trigger.get("to_state")
        else:  # state_changed
            data = event.get("data", {})
            entity_id, old, new = data.get("entity_id"), data.get("old_state"), data.get("new_state")
        if entity_id:
            events.publish(f"{self.name}/state/{entity_id}", state_event(entity_id, old, new))
