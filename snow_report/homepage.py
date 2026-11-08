from django.core.cache import cache

from hub.plugins import INFO, ON, Status

from .views import fetch_weather_html, parse_weather_html, sanitize_number

CACHE_KEY = "snow_report:homepage"
CACHE_TTL = 15 * 60


def _summary():
    data = parse_weather_html(fetch_weather_html(), "metric")
    for snow in data["snow_conditions"]:
        amount = sanitize_number(snow["value"])
        if amount is not None:
            return {"period": snow["period"], "cm": round(amount)}
    return {"description": data["today_description"]}


def status():
    summary = cache.get(CACHE_KEY)
    if summary is None:
        summary = _summary()
        cache.set(CACHE_KEY, summary, CACHE_TTL)
    if "cm" in summary:
        period = summary['period']
        if 'new' in period.lower():
            text = f"{summary['cm']} cm new snow"
        else:
            text = f"{summary['cm']} cm in {period.lower()}"
        return Status(text, ON if summary["cm"] > 0 else INFO)
    if summary.get("description"):
        return Status(summary["description"])
    return None
