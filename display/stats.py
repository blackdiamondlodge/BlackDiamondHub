"""Numbers for the screensaver's info strip.

Every source is optional: a stat whose data is missing is left out.
"""
import logging
import math
from datetime import datetime, time, timedelta, timezone

from .season import by_date, next_start

log = logging.getLogger(__name__)

# The lodge, for sunrise and sunset.
LAT, LON = 50.884, -119.885
MINUS = "\u2212"


def gather():
    """Fetch what the stats need: ``{"resort": ..., "lifts": ...}``, each possibly None."""
    data = {"resort": None, "lifts": None}
    try:
        from snow_report.resort import get_resort

        data["resort"] = get_resort()
    except Exception as exc:
        log.debug("no snow report: %s", exc)
    try:
        from lift_status.scraper import get_lift_status

        data["lifts"] = (get_lift_status() or {}).get("summary")
    except Exception as exc:
        log.debug("no lift status: %s", exc)
    return data


def lifts_open(data):
    lifts = data.get("lifts") or {}
    return lifts.get("lifts_open") if lifts.get("lifts_total") else None


def _temp(c):
    n = round(c)
    return f"{MINUS if n < 0 else ''}{abs(n)}°C"


def _temps(data):
    return [t for t in ((data.get("resort") or {}).get("temperatures") or []) if t.get("c") is not None]


def _named(rows, word):
    return next((r for r in rows if word in (r.get("name") or "").lower()), None)


def _top(rows):
    return _named(rows, "top of the world") or max(rows, key=lambda r: r.get("elevation_m") or 0, default=None)


def _bottom(rows):
    return _named(rows, "valley") or min(rows, key=lambda r: r.get("elevation_m") or 0, default=None)


def sun_times(day, lat=LAT, lon=LON):
    """Sunrise and sunset on ``day`` as UTC datetimes (NOAA's approximation)."""
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl))
              - math.tan(phi) * math.tan(decl))
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    midnight = datetime.combine(day, time(), tzinfo=timezone.utc)
    rise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    sets = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return rise, sets


def _of(open_, total):
    return f"{open_} of {total}" if total else None


def stat(key, data, today, starts):
    """One stat as ``{"label", "value"}`` (or ``{"label", "time"}`` with an ISO UTC time), or None."""
    resort = data.get("resort") or {}
    lifts = data.get("lifts") or {}

    if key in ("temp_top", "temp_mid", "temp_village"):
        rows = _temps(data)
        row = {"temp_top": _top, "temp_village": _bottom,
               "temp_mid": lambda r: _named(r, "mid")}[key](rows)
        label = {"temp_top": "Up top", "temp_mid": "Mid-mountain", "temp_village": "At the lodge"}[key]
        return {"label": label, "value": _temp(row["c"])} if row else None

    if key == "new_snow":
        row = next((r for r in resort.get("new_snow") or [] if r.get("period") == "48 Hr"), None)
        if row and row.get("cm") is not None:
            return {"label": "New snow, 48h", "value": f"{row['cm']} cm"}
        return None

    if key == "base":
        row = next((r for r in resort.get("base") or [] if r.get("cm") is not None), None)
        return {"label": "Base depth", "value": f"{row['cm']} cm"} if row else None

    if key == "wind_top":
        rows = [w for w in resort.get("wind") or [] if w.get("kph") is not None]
        row = _top(rows)
        if row:
            return {"label": "Wind up top", "value": f"{row['kph']} km/h {row.get('direction') or ''}".strip()}
        return None

    if key == "runs_open":
        value = _of(lifts.get("trails_open"), lifts.get("trails_total"))
        return {"label": "Runs open", "value": value} if value else None

    if key == "lifts_open":
        value = _of(lifts.get("lifts_open"), lifts.get("lifts_total"))
        return {"label": "Lifts open", "value": value} if value else None

    if key == "groomed":
        if lifts.get("groomed") is None or not lifts.get("trails_total"):
            return None
        return {"label": "Runs groomed", "value": str(lifts["groomed"])}

    if key in ("sunrise", "sunset"):
        rise, sets = sun_times(today)
        when = rise if key == "sunrise" else sets
        return {"label": key.capitalize(), "time": when.isoformat().replace("+00:00", "Z")}

    if key == "days_until_lifts":
        if lifts_open(data) != 0 or by_date(today, starts) == "winter":
            return None
        days = (next_start(today, starts["winter"]) - today).days
        return {"label": "Until lifts open", "value": "1 day" if days == 1 else f"{days} days"}

    return None


def collect(keys, data, today, starts):
    out = []
    for key in keys:
        if key == "none":
            continue
        try:
            item = stat(key, data, today, starts)
        except Exception as exc:
            log.warning("display stat %s failed: %s", key, exc)
            item = None
        if item:
            out.append(item)
    return out
