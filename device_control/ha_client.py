"""Compatibility shim: the Home Assistant client now lives in hub.ha_client."""

import requests  # noqa: F401  (kept so tests can patch device_control.ha_client.requests)

from hub.ha_client import (  # noqa: F401
    TIMEOUT,
    HAError,
    call_service,
    get_all_states,
    get_entity_state,
    get_entity_states,
    get_history,
    get_static,
    ws_commands,
)
