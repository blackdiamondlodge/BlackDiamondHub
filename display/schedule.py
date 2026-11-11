"""Night mode: the hours the lodge display goes dark."""
from datetime import datetime, timezone

from .season import LODGE_TZ


def parse_hhmm(text):
    """``"23:00"`` -> minutes after midnight; raises ValueError."""
    try:
        hours, minutes = (int(part) for part in str(text).strip().split(":"))
    except ValueError:
        raise ValueError("Use HH:MM, like 23:00") from None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ValueError("Use HH:MM, like 23:00")
    return hours * 60 + minutes


def is_night(minute, start, end):
    """Whether ``minute`` of the day falls in [start, end), wrapping past midnight."""
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def lodge_minute(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(LODGE_TZ)
    return local.hour * 60 + local.minute


def window():
    """The night window as ``{"from": min, "until": min, "offset": utc offset min}``, or None when off."""
    from .options import DEFAULT_NIGHT, value

    if not value("night"):
        return None
    out = {"offset": int(LODGE_TZ.utcoffset(None).total_seconds() // 60)}
    for key in ("from", "until"):
        try:
            out[key] = parse_hhmm(value(f"night_{key}"))
        except ValueError:
            out[key] = parse_hhmm(DEFAULT_NIGHT[key])
    return out