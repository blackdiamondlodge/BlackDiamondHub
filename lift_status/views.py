from django.shortcuts import render
from .scraper import get_lift_status, ZONES


def lift_status_view(request):
    """Render the page shell immediately (map, tabs, spinner).

    The actual lift/trail data is fetched asynchronously via
    lift_status_data_view so the page feels instant.
    """
    # Pass just the static zone info so tabs can be rendered
    zones_shell = [{"key": key, "label": label} for key, label in ZONES]
    return render(request, "lift_status/lift_status.html", {"zones_shell": zones_shell})


def lift_status_data_view(request):
    """Return the data panels as an HTML partial (fetched via AJAX)."""
    data = get_lift_status()
    return render(request, "lift_status/lift_status_data.html", data)
