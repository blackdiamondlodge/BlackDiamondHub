"""The display app's settings and the choices behind them."""
from bdh_sdk.plugins import BOOL, CHOICE, INT, Setting
from bdh_sdk.settings import app_setting

APP = "display"

SEASONS = (("winter", "Winter"), ("spring", "Spring"), ("summer", "Summer"), ("fall", "Fall"))
SEASON_IDS = tuple(s for s, _ in SEASONS)

SOURCES = (
    ("stock", "Stock illustration"),
    ("photos", "My photos"),
    ("cam", "Live cam"),
    ("mix", "Mix"),
)

STATS = (
    ("temp_top", "Temp up top"),
    ("temp_mid", "Temp mid-mountain"),
    ("temp_village", "Temp at the lodge"),
    ("new_snow", "New snow, 48h"),
    ("base", "Base depth"),
    ("runs_open", "Runs open"),
    ("lifts_open", "Lifts open"),
    ("groomed", "Runs groomed"),
    ("wind_top", "Wind up top"),
    ("sunrise", "Sunrise"),
    ("sunset", "Sunset"),
    ("days_until_lifts", "Days until lifts open"),
)
SLOT_CHOICES = STATS + (("none", "Nothing"),)
SLOTS = 4

DEFAULT_SLOTS = {
    "winter": ("temp_top", "temp_village", "new_snow", "runs_open"),
    "spring": ("temp_top", "temp_village", "base", "sunset"),
    "summer": ("temp_top", "temp_village", "lifts_open", "sunset"),
    "fall": ("temp_top", "temp_village", "days_until_lifts", "sunset"),
}
DEFAULT_STARTS = {"winter": "11-21", "spring": "03-15", "summer": "06-01", "fall": "09-15"}


def _settings():
    out = [
        Setting("idle_minutes", "Screensaver after", INT, 10, "No touches for this long", minimum=1,
                maximum=120, unit="min"),
        Setting("burn_in", "Burn-in protection", BOOL, True, "Slow pixel shift on every screen"),
        Setting("winter_on_lifts", "Winter starts when lifts open", BOOL, True,
                "Otherwise use the dates below"),
        Setting("rotate_minutes", "Change every", INT, 3, minimum=1, maximum=60, unit="min"),
        Setting("cam", "Live cam", help="Webcam slug; empty picks Sunburst Express", default=""),
    ]
    for season, label in SEASONS:
        out.append(Setting(f"{season}_start", f"{label} starts", default=DEFAULT_STARTS[season],
                           help="Month and day, MM-DD"))
        out.append(Setting(f"source_{season}", f"{label} background", CHOICE, "stock", choices=SOURCES))
        for n in range(1, SLOTS + 1):
            out.append(Setting(f"slot_{season}_{n}", f"{label} info slot {n}", CHOICE,
                               DEFAULT_SLOTS[season][n - 1], choices=SLOT_CHOICES))
    return tuple(out)


SETTINGS = _settings()
BY_KEY = {s.key: s for s in SETTINGS}


def value(key):
    """The current value of a display setting, parsed to its type."""
    setting = BY_KEY[key]
    raw = app_setting(APP, key, setting.default)
    if isinstance(raw, str):
        try:
            return setting.parse(raw)
        except ValueError:
            return setting.default
    return raw


def starts():
    """Season start dates as ``{season: "MM-DD"}``, falling back to defaults when invalid."""
    from .season import parse_mmdd

    out = {}
    for season in SEASON_IDS:
        text = value(f"{season}_start")
        try:
            parse_mmdd(text)
        except ValueError:
            text = DEFAULT_STARTS[season]
        out[season] = text
    return out
