"""
Step definitions for Vacation Mode and Home Mode.

Each step is a dict with:
- alias: Human-readable name
- icon: Font Awesome icon class
- actions: List of HA API calls to execute sequentially
  Each action has:
    - action: HA service to call (e.g. "climate/set_temperature")
    - data: Payload to send
    - delay_after: Optional delay in seconds after this action

Seasonal behaviour
------------------
The AECO-1988 heat pump is a changeover system: it produces EITHER hot water
(heating the buffer/floors) OR chilled water (cooling the floors), never both.
The active mode is selected by the mutually-exclusive permanent-demand switches
(``switch.aeco_1988_permanent_heat_demand`` / ``permanent_cool_demand``) — the
``heat/cool/auto`` select is not used. While in one mode, the OTHER tank's
number entities (min/max/target/outdoor_reset) report ``unavailable``, so the
mode must be flipped (and given a few seconds to settle) BEFORE its tank
entities can be written.

Because of this, the HVAC steps are built per-season. ``build_vacation_steps``
and ``build_home_steps`` take a ``season`` ("heating" or "cooling"); the season
is chosen at run time from the daily-average outdoor temperature (see
``executor.get_current_season``). Everything else (water heater, hot tub, TVs,
fridge/freezer, garage) is season-independent.

The zone thermostats are Google Nest units and are rate-limited, so each
``climate/set_temperature`` call is a separate action with a small
``delay_after`` — they must never be batched into one multi-entity call.
"""

SEASON_HEATING = "heating"
SEASON_COOLING = "cooling"

# Zone thermostats (Nest — rate limited, set one at a time with a delay).
ZONE_THERMOSTATS = [
    ("climate.master_bedroom", "Master Bedroom"),
    ("climate.basement_bunk_rooms", "Basement Bunk Rooms"),
    ("climate.main_floor", "Main Floor"),
    ("climate.basement_master", "Basement Master"),
    ("climate.ski_room", "Ski Room"),
]

# Per-season zone air setpoints (°C).
#   heating: warm the house; ski room a touch cooler.
#   cooling: single comfort/setback target for all zones.
ZONE_SETPOINTS = {
    SEASON_HEATING: {
        "home": {"climate.ski_room": 19, "_default": 20},
        "away": {"_default": 12},
    },
    SEASON_COOLING: {
        "home": {"_default": 22},
        "away": {"_default": 28},
    },
}

# AECO changeover switches.
_HEAT_DEMAND = "switch.aeco_1988_permanent_heat_demand"
_COOL_DEMAND = "switch.aeco_1988_permanent_cool_demand"

# Seconds to wait after flipping the changeover before writing tank entities.
MODE_SWITCH_DELAY = 10


def _zone_setpoint(season, occupancy, entity_id):
    """Resolve the air setpoint for a zone under a season/occupancy."""
    table = ZONE_SETPOINTS[season][occupancy]
    return table.get(entity_id, table["_default"])


def _mode_changeover_actions(season):
    """
    Actions that flip the AECO changeover to the desired season.

    Turns the unwanted permanent-demand switch OFF first, then the desired one
    ON, then waits MODE_SWITCH_DELAY so the (previously unavailable) tank
    entities become writable.
    """
    if season == SEASON_COOLING:
        off_sw, on_sw, label = _HEAT_DEMAND, _COOL_DEMAND, "cooling"
    else:
        off_sw, on_sw, label = _COOL_DEMAND, _HEAT_DEMAND, "heating"

    return [
        {
            "action": "switch/turn_off",
            "data": {"entity_id": off_sw},
            "description": f"Clearing opposite demand (→ {label})",
            "delay_after": 1,
        },
        {
            "action": "switch/turn_on",
            "data": {"entity_id": on_sw},
            "description": f"Setting system to {label.upper()} mode",
            "delay_after": MODE_SWITCH_DELAY,
        },
    ]


def _heatpump_setup_step(season, occupancy):
    """Build the 'Heat Pump Setup' step for a season/occupancy."""
    actions = _mode_changeover_actions(season)

    if season == SEASON_HEATING:
        icon = "fas fa-fire"
        alias = "Heat Pump Setup — Heating"
        if occupancy == "home":
            actions += [
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.aeco_1988_hot_tank_outdoor_reset"},
                    "description": "Enabling outdoor reset",
                    "delay_after": 2,
                },
                {
                    "action": "number/set_value",
                    "data": {
                        "entity_id": "number.aeco_1988_hot_tank_outdoor_reset",
                        "value": "-20",
                    },
                    "description": "Setting outdoor reset to -20°C",
                    "verify_delay": 10,
                },
                {
                    "action": "number/set_value",
                    "data": {
                        "entity_id": "number.aeco_1988_hot_tank_min_temperature",
                        "value": "27",
                    },
                    "description": "Setting hot tank min to 27°C",
                    "verify_delay": 10,
                },
                {
                    "action": "number/set_value",
                    "data": {
                        "entity_id": "number.aeco_1988_hot_tank_max_temperature",
                        "value": "38",
                    },
                    "description": "Setting hot tank max to 38°C",
                    "verify_delay": 10,
                },
            ]
        else:  # away
            actions += [
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.aeco_1988_hot_tank_outdoor_reset"},
                    "description": "Disabling outdoor reset",
                    "delay_after": 2,
                },
                {
                    "action": "number/set_value",
                    "data": {
                        "entity_id": "number.aeco_1988_hot_tank_target_temperature",
                        "value": "28",
                    },
                    "description": "Setting hot tank target to 28°C",
                    "verify_delay": 10,
                },
                {
                    "action": "number/set_value",
                    "data": {
                        "entity_id": "number.aeco_1988_backup_differential",
                        "value": "8",
                    },
                    "description": "Setting backup differential to 8°C",
                    "verify_delay": 10,
                },
            ]
    else:  # cooling
        icon = "fas fa-snowflake"
        alias = "Heat Pump Setup — Cooling"
        # Fixed cold-tank target: outdoor reset OFF so the tank holds a constant
        # chilled-water temperature. The min/max entities only exist while
        # outdoor reset is ON (they bound the reset curve), so we do NOT write
        # them here — a reset curve adds no value at these warm targets, and the
        # dew-point mixer valve protects the floor.
        #
        # The target must stay >= 13.5°C: the AECO clears cooling demand only
        # once the tank reaches target - 1.5°C, but the heat pump's own floor is
        # 12°C, so a target of 12 could never satisfy (demand would never clear).
        # 14.4 (the system's original home setpoint) shuts off at ~12.9°C.
        cold_target = "14.4" if occupancy == "home" else "18"
        actions += [
            {
                "action": "switch/turn_off",
                "data": {"entity_id": "switch.aeco_1988_cold_tank_outdoor_reset"},
                "description": "Disabling cold tank outdoor reset",
                "delay_after": 2,
            },
            {
                "action": "number/set_value",
                "data": {
                    "entity_id": "number.aeco_1988_cold_tank_target_temperature",
                    "value": cold_target,
                },
                "description": f"Setting cold tank target to {cold_target}°C",
                "verify_delay": 10,
            },
        ]

    return {"alias": alias, "icon": icon, "actions": actions}


def _thermostats_step(season, occupancy, alias, icon, clear_presets=False, extra_actions=None):
    """
    Build a thermostat step. Nest units are rate-limited, so each zone is a
    separate action with a delay. Optionally clears presets first (home mode)
    and appends extra actions (e.g. garage/storage on arrival).
    """
    hvac_mode = "cool" if season == SEASON_COOLING else "heat"
    actions = []

    if clear_presets:
        actions.append(
            {
                "action": "climate/set_preset_mode",
                "data": {
                    "entity_id": [e for e, _ in ZONE_THERMOSTATS],
                    "preset_mode": "none",
                },
                "description": "Clearing presets on all thermostats",
                "delay_after": 2,
            }
        )

    for entity_id, name in ZONE_THERMOSTATS:
        temp = _zone_setpoint(season, occupancy, entity_id)
        actions.append(
            {
                "action": "climate/set_temperature",
                "data": {
                    "entity_id": entity_id,
                    "temperature": temp,
                    "hvac_mode": hvac_mode,
                },
                "description": f"{name} → {temp}°C ({hvac_mode})",
                "delay_after": 1,
            }
        )

    if extra_actions:
        actions.extend(extra_actions)

    return {"alias": alias, "icon": icon, "actions": actions}


# ============================================================
# SEASON-INDEPENDENT STEPS
# ============================================================
def _vacation_static_prefix():
    return [
        {
            "alias": "Turn Off Water Heater",
            "icon": "fas fa-fire",
            "actions": [
                {
                    "action": "climate/set_preset_mode",
                    "data": {
                        "entity_id": "climate.econet_hpwh",
                        "preset_mode": "Off",
                    },
                    "description": "Setting water heater to Off",
                },
            ],
        },
        {
            "alias": "Set Hot Tub to Vacation Mode",
            "icon": "fas fa-hot-tub-person",
            "actions": [
                {
                    "action": "climate/set_preset_mode",
                    "data": {
                        "entity_id": "climate.hot_tub_heater",
                        "preset_mode": "Away From Home",
                    },
                    "description": "Setting hot tub to Away From Home",
                },
            ],
        },
    ]


def _vacation_static_suffix():
    return [
        {
            "alias": "Set Garage Heaters to 5°C",
            "icon": "fas fa-warehouse",
            "actions": [
                {
                    "action": "climate/set_temperature",
                    "data": {
                        "entity_id": "climate.garage_thermostat_thermostat",
                        "temperature": 5,
                    },
                    "description": "Garage → 5°C",
                    "delay_after": 1,
                },
                {
                    "action": "climate/set_temperature",
                    "data": {
                        "entity_id": "climate.storage_room_thermostat_thermostat",
                        "temperature": 5,
                    },
                    "description": "Storage Room → 5°C",
                },
            ],
        },
        {
            "alias": "Set Fridge & Freezer to Vacation Mode",
            "icon": "fas fa-icicles",
            "actions": [
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.freezer_eco_mode"},
                    "description": "Enabling freezer eco mode",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.freezer_dispenser"},
                    "description": "Disabling freezer dispenser",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.refrigerator_eco_mode"},
                    "description": "Enabling fridge eco mode",
                },
            ],
        },
        {
            "alias": "Turn Off Televisions & Sonos",
            "icon": "fas fa-tv",
            "actions": [
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.living_room_tv_socket_1"},
                    "description": "Living Room TV",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.living_room_tv_socket_2"},
                    "description": "Living Room Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.basement_master_tv_socket_1"},
                    "description": "Basement Master TV",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.media_room_tv_socket_1"},
                    "description": "Games Room TV",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.media_room_tv_socket_2"},
                    "description": "Games Room Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.office_tv_socket_1"},
                    "description": "Office TV",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.office_tv_socket_2"},
                    "description": "Office Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.master_bedroom_tv_socket_1"},
                    "description": "Master Bedroom TV",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.master_bedroom_tv_socket_2"},
                    "description": "Master Bedroom Sonos",
                },
            ],
        },
        {
            "alias": "Turn Off Patio Heaters",
            "icon": "fas fa-fire-flame-curved",
            "actions": [
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.patio_deck_heaters"},
                    "description": "Turning off patio deck heaters",
                },
            ],
        },
        {
            "alias": "Turn Off Fireplaces",
            "icon": "fas fa-fire",
            "actions": [
                {
                    "action": "climate/set_hvac_mode",
                    "data": {
                        "entity_id": "climate.master_bedroom_2",
                        "hvac_mode": "off",
                    },
                    "description": "Master Bedroom fireplace heater → off",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.master_bedroom"},
                    "description": "Master Bedroom fireplace flames → off",
                    "delay_after": 1,
                },
                {
                    "action": "climate/set_hvac_mode",
                    "data": {
                        "entity_id": "climate.living_room_fireplace",
                        "hvac_mode": "off",
                    },
                    "description": "Living Room fireplace heater → off",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.living_room_fireplace"},
                    "description": "Living Room fireplace flames → off",
                },
            ],
        },
        {
            "alias": "Enable Home Away Mode",
            "icon": "fas fa-plane-departure",
            "actions": [
                {
                    "action": "input_boolean/turn_on",
                    "data": {"entity_id": "input_boolean.home_away_mode_enabled"},
                    "description": "Enabling away mode flag",
                },
            ],
        },
    ]


def _home_static_prefix():
    return [
        {
            "alias": "Start Water Heater",
            "icon": "fas fa-fire",
            "actions": [
                {
                    "action": "climate/set_preset_mode",
                    "data": {
                        "entity_id": "climate.econet_hpwh",
                        "preset_mode": "Eco Mode",
                    },
                    "description": "Setting water heater to Eco Mode",
                },
            ],
        },
        {
            "alias": "Start Hot Tub",
            "icon": "fas fa-hot-tub-person",
            "actions": [
                {
                    "action": "climate/set_preset_mode",
                    "data": {
                        "entity_id": "climate.hot_tub_heater",
                        "preset_mode": "Standard",
                    },
                    "description": "Setting hot tub to Standard mode",
                },
            ],
        },
    ]


def _home_static_suffix():
    return [
        {
            "alias": "Setup Fridge/Freezer for Arrival",
            "icon": "fas fa-icicles",
            "actions": [
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.freezer_eco_mode"},
                    "description": "Disabling freezer eco mode",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.freezer_dispenser"},
                    "description": "Enabling freezer dispenser",
                },
                {
                    "action": "switch/turn_off",
                    "data": {"entity_id": "switch.refrigerator_eco_mode"},
                    "description": "Disabling fridge eco mode",
                },
            ],
        },
        {
            "alias": "Turn On Televisions & Sonos",
            "icon": "fas fa-tv",
            "actions": [
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.living_room_tv_socket_1"},
                    "description": "Living Room TV",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.living_room_tv_socket_2"},
                    "description": "Living Room Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.basement_master_tv_socket_1"},
                    "description": "Basement Master TV",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.media_room_tv_socket_1"},
                    "description": "Games Room TV",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.media_room_tv_socket_2"},
                    "description": "Games Room Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.office_tv_socket_1"},
                    "description": "Office TV",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.office_tv_socket_2"},
                    "description": "Office Sonos",
                    "delay_after": 1,
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.master_bedroom_tv_socket_1"},
                    "description": "Master Bedroom TV",
                },
                {
                    "action": "switch/turn_on",
                    "data": {"entity_id": "switch.master_bedroom_tv_socket_2"},
                    "description": "Master Bedroom Sonos",
                },
            ],
        },
        {
            "alias": "Disable Home Away Mode",
            "icon": "fas fa-house-flag",
            "actions": [
                {
                    "action": "input_boolean/turn_off",
                    "data": {"entity_id": "input_boolean.home_away_mode_enabled"},
                    "description": "Disabling away mode flag",
                },
            ],
        },
    ]


# Garage/storage heaters are heat-only; they stay set to their heating values
# in both seasons (in cooling season they simply never call). Appended to the
# arrival thermostat step.
_HOME_GARAGE_ACTIONS = [
    {
        "action": "climate/set_temperature",
        "data": {
            "entity_id": "climate.garage_thermostat_thermostat",
            "temperature": 10,
        },
        "description": "Garage → 10°C",
        "delay_after": 1,
    },
    {
        "action": "climate/set_temperature",
        "data": {
            "entity_id": "climate.storage_room_thermostat_thermostat",
            "temperature": 10,
        },
        "description": "Storage Room → 10°C",
    },
]


# ============================================================
# BUILDERS
# ============================================================
def build_vacation_steps(season=SEASON_HEATING):
    """Steps to put the lodge into vacation (away) mode for the given season."""
    thermo_alias = (
        "Set Thermostats to Away Cool (28°C)"
        if season == SEASON_COOLING
        else "Set Thermostats to Away Heat (12°C)"
    )
    thermo_icon = "fas fa-snowflake" if season == SEASON_COOLING else "fas fa-temperature-arrow-down"
    return (
        _vacation_static_prefix()
        + [
            _heatpump_setup_step(season, "away"),
            _thermostats_step(season, "away", thermo_alias, thermo_icon),
        ]
        + _vacation_static_suffix()
    )


def build_home_steps(season=SEASON_HEATING):
    """Steps to prepare the lodge for arrival (home) for the given season."""
    if season == SEASON_COOLING:
        thermo_alias = "Set Thermostats to Home Cool (22°C)"
        thermo_icon = "fas fa-snowflake"
    else:
        thermo_alias = "Set Thermostats to Home Heat (20°C)"
        thermo_icon = "fas fa-house-chimney"
    return (
        _home_static_prefix()
        + [
            _heatpump_setup_step(season, "home"),
            _thermostats_step(
                season,
                "home",
                thermo_alias,
                thermo_icon,
                clear_presets=True,
                extra_actions=_HOME_GARAGE_ACTIONS,
            ),
        ]
        + _home_static_suffix()
    )


# Backward-compatible module-level constants (default = heating variant).
VACATION_STEPS = build_vacation_steps(SEASON_HEATING)
HOME_STEPS = build_home_steps(SEASON_HEATING)
