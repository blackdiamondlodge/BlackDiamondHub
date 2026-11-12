"""Data apps provide to the rest of the hub (``PluginSpec.provides``).

Providers run in the same worker pool as status hooks, with a short deadline,
and their results are cached; a failing or slow provider serves its last good
result, and one that has never answered is simply left out. Results are
checked here, so a consumer can trust the shapes it gets.
"""
import logging
from datetime import timezone
from functools import partial

from bdh_sdk.provides import BACKGROUNDS, CAPABILITIES, SEASON, STATS, Background, SeasonHint, Stat

from .modes import plugins
from .status import _gather

logger = logging.getLogger(__name__)

TTL = 60
TIMEOUT = 2.0

GRACE = 0.3

_warned = set()


def app_label(spec):
    return spec.tiles[0].title if spec.tiles else spec.id.replace("_", " ").title()


def providers(capability):
    """Installed specs providing ``capability``, in plugin order."""
    out = []
    for spec in plugins():
        provides = getattr(spec, "provides", None) or {}
        for name in provides:
            if name not in CAPABILITIES and (spec.id, name) not in _warned:
                _warned.add((spec.id, name))
                logger.info("%s provides unknown capability %r; ignored", spec.id, name)
        if capability in provides:
            out.append(spec)
    return out


def _iso(when):
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stats_value(allowed, result):
    out = {}
    for stat in list(result or ()):
        if not isinstance(stat, Stat):
            raise TypeError(f"stats provider returned {type(stat).__name__}")
        if stat.key not in allowed:
            logger.warning("Skipping undeclared stat %r", stat.key)
            continue
        if stat.key in out:
            continue
        item = {"label": stat.label, "order": stat.order}
        if stat.time is not None:
            item["time"] = _iso(stat.time)
        else:
            item["value"] = str(stat.value)
        out[stat.key] = item
    return out


def _backgrounds_value(result):
    out, seen = [], set()
    for bg in list(result or ()):
        if not isinstance(bg, Background):
            raise TypeError(f"backgrounds provider returned {type(bg).__name__}")
        if bg.id in seen or not bg.image_url:
            continue
        seen.add(bg.id)
        out.append({"id": bg.id, "label": bg.label, "url": bg.image_url,
                    "refresh_seconds": bg.refresh_seconds, "live": bg.live})
    return out


def _season_value(result):
    if result is None:
        return None
    if not isinstance(result, SeasonHint):
        raise TypeError(f"season provider returned {type(result).__name__}")
    return {"season": result.season, "reason": result.reason}


def _run(capability, specs, convert, timeout):
    kind = f"provide:{capability}"
    jobs = [(kind, s.id, s.provides[capability], convert(s), TTL) for s in specs]
    results = _gather(jobs, timeout, grace=min(GRACE, timeout)) if jobs else {}
    return [(s, results[(kind, s.id)]["value"]) for s in specs
            if (kind, s.id) in results and not results[(kind, s.id)].get("missing")]


def stat_catalogue():
    """``[(qualified id, label, app label)]`` for every declared stat, without calling providers."""
    return [(f"{s.id}.{key}", label, app_label(s))
            for s in providers(STATS) for key, label in s.stat_keys]


def stat_owners():
    """Plugin ids that provide stats."""
    return {s.id for s in providers(STATS)}


def stats(plugin_ids=None, timeout=TIMEOUT):
    """``{"<plugin>.<key>": {"label", "value" | "time", "order"}}`` from stat providers.

    With ``plugin_ids``, only those providers are called.
    """
    specs = [s for s in providers(STATS) if plugin_ids is None or s.id in plugin_ids]
    allowed = lambda s: partial(_stats_value, frozenset(k for k, _ in s.stat_keys))  # noqa: E731
    out = {}
    for spec, value in _run(STATS, specs, allowed, timeout):
        for key, item in (value or {}).items():
            out[f"{spec.id}.{key}"] = item
    return out


def backgrounds(timeout=TIMEOUT):
    """Every provided background, ids qualified as ``"<plugin>.<id>"``."""
    out = []
    for spec, value in _run(BACKGROUNDS, providers(BACKGROUNDS), lambda s: _backgrounds_value, timeout):
        out.extend({**bg, "id": f"{spec.id}.{bg['id']}", "app": app_label(spec)} for bg in value or ())
    return out


def season_hints(timeout=TIMEOUT):
    """``[{"app", "season", "reason"}]`` from season providers that currently give a hint."""
    return [{"app": app_label(spec), **value}
            for spec, value in _run(SEASON, providers(SEASON), lambda s: _season_value, timeout)
            if value]
