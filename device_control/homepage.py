from hub.plugins import ALL_MODES, INFO, ON, Shortcut, Status

from .ha_client import call_service, get_all_states
from .views import _napoleon_registry

FIREPLACES_OFF = "fireplaces_off"


def _fireplaces():
    """Napoleon fireplace climate entities with their current state."""
    registry = _napoleon_registry()
    climates = {
        eid for eid in registry["entities"] if eid.startswith("climate.")
    }
    return [s for s in get_all_states() if s.get("entity_id") in climates]


def _is_on(state):
    return state.get("state") not in ("off", "unavailable", "unknown", None)


def status():
    fireplaces = _fireplaces()
    if not fireplaces:
        return None
    on = sum(1 for s in fireplaces if _is_on(s))
    if on == 0:
        return Status("Fireplaces off" if len(fireplaces) > 1 else "Fireplace off", INFO)
    if len(fireplaces) == 1:
        return Status("Fireplace on", ON)
    return Status(f"{on} of {len(fireplaces)} fireplaces on", ON)


def shortcuts():
    fireplaces = _fireplaces()
    if not fireplaces:
        return []
    return [
        Shortcut(
            id=FIREPLACES_OFF,
            title="Fireplaces off" if len(fireplaces) > 1 else "Fireplace off",
            icon="fa-solid fa-fire",
            order=50,
            modes=ALL_MODES,
        )
    ]


def run_shortcut(shortcut_id):
    if shortcut_id != FIREPLACES_OFF:
        raise ValueError(shortcut_id)
    lit = [s["entity_id"] for s in _fireplaces() if _is_on(s)]
    for entity_id in lit:
        ok, err = call_service("climate", "turn_off", entity_id)
        if not ok:
            raise RuntimeError(err)
    if not lit:
        return "Fireplaces are already off"
    return None
