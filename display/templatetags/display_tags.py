from django import template
from django.urls import NoReverseMatch, reverse

register = template.Library()


@register.inclusion_tag("display/overlay.html")
def screensaver():
    """The screensaver and burn-in shifter, on every page of the hub."""
    from ..options import value

    try:
        api = reverse("display_saver_api")
    except NoReverseMatch:  # display app not loaded
        return {"enabled": False}
    try:
        config = {"idle_minutes": value("idle_minutes"), "burn_in": value("burn_in")}
    except Exception:
        config = {"idle_minutes": 10, "burn_in": True}
    return {"enabled": True, "config": {**config, "api": api}}
