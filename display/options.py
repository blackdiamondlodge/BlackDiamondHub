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

SLOTS = 4

# Stored as bare keys, normalized by catalog.normalize. Sites without the
# mountain apps get GENERIC_SLOTS instead.
DEFAULT_SLOTS = {
    "winter": ("temp_top", "temp_village", "new_snow", "runs_open"),
    "spring": ("temp_top", "temp_village", "base", "sunset"),
    "summer": ("temp_top", "temp_village", "lifts_open", "sunset"),
    "fall": ("temp_top", "temp_village", "days_until_lifts", "sunset"),
}
GENERIC_SLOTS = ("weather.temp", "weather.sunrise", "weather.sunset", "none")
MOUNTAIN_APPS = ("snow_report", "lift_status")
DEFAULT_STARTS = {"winter": "11-21", "spring": "03-15", "summer": "06-01", "fall": "09-15"}
DEFAULT_NIGHT = {"from": "23:00", "until": "06:00"}


def _settings():
    out = [
        Setting("idle_minutes", "Screensaver after", INT, 10, "No touches for this long", minimum=1,
                maximum=120, unit="min"),
        Setting("burn_in", "Burn-in protection", BOOL, True, "Slow pixel shift on every screen"),
        Setting("photo_caption", "Show photo date", BOOL, False, "Month and year in the corner of your photos"),
        Setting("night", "Dark overnight", BOOL, True, "The screensaver goes black between these times"),
        Setting("night_from", "Dark from", default=DEFAULT_NIGHT["from"], help="HH:MM, 24-hour"),
        Setting("night_until", "Dark until", default=DEFAULT_NIGHT["until"], help="HH:MM, 24-hour"),
        Setting("winter_on_lifts", "Let apps bring winter forward", BOOL, True,
                "Otherwise use the dates below"),
        Setting("rotate_minutes", "Change every", INT, 3, minimum=1, maximum=60, unit="min"),
        Setting("cam", "Live cam", help="Background id; empty picks the first", default=""),
    ]
    for season, label in SEASONS:
        out.append(Setting(f"{season}_start", f"{label} starts", default=DEFAULT_STARTS[season],
                           help="Month and day, MM-DD"))
        out.append(Setting(f"source_{season}", f"{label} background", CHOICE, "stock", choices=SOURCES))
        for n in range(1, SLOTS + 1):
            out.append(Setting(f"slot_{season}_{n}", f"{label} info slot {n}", default="",
                               help="Stat id; empty uses the site default"))
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


def default_slot(season, n):
    """The info-strip stat a slot shows when it was never set, for this site's apps."""
    from .catalog import installed, normalize

    mountain = any(app in installed() for app in MOUNTAIN_APPS)
    return normalize((DEFAULT_SLOTS[season] if mountain else GENERIC_SLOTS)[n - 1])


def slot(season, n, raw=None):
    """A slot's stat id, normalized; ``raw`` overrides the saved value."""
    from .catalog import normalize

    key = normalize(value(f"slot_{season}_{n}") if raw is None else raw)
    return key or default_slot(season, n)
