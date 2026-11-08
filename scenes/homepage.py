from urllib.parse import urljoin

import requests
from django.conf import settings

from hub.plugins import ALL_MODES, INFO, ON, Shortcut, Status

from .views import HEADERS, activate_scene, get_scenes

SCENE_PREFIX = "scene."


def status():
    url = urljoin(settings.HOMEASSISTANT_URL, "/api/states")
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    # Light groups list their members in an entity_id attribute; skip them
    # so each bulb is counted once.
    on = sum(
        1 for s in response.json()
        if s["entity_id"].startswith("light.")
        and s.get("state") == "on"
        and "entity_id" not in s.get("attributes", {})
    )
    if on == 0:
        return Status("All lights off", INFO)
    return Status(f"{on} light{'s' if on != 1 else ''} on", ON)


def shortcuts():
    return [
        Shortcut(
            id=scene["id"].removeprefix(SCENE_PREFIX),
            title=scene["name"],
            icon=scene["icon"],
            order=10,
            modes=ALL_MODES,
        )
        for scene in get_scenes()
    ]


def run_shortcut(shortcut_id):
    activate_scene(SCENE_PREFIX + shortcut_id)
    return None
