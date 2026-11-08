from hub.plugins import ON, Status

from .scraper import get_lift_status


def status():
    lifts = get_lift_status()["lifts"]
    if not lifts:
        return None
    open_count = sum(1 for lift in lifts if lift["status"] == "open")
    if open_count == 0:
        return Status("All lifts closed")
    return Status(f"{open_count} of {len(lifts)} lifts open", ON)
