"""Discovers and validates hub plugins.

Built-in apps are listed explicitly by dotted path to their ``spec``.
Separately installed apps register a ``blackdiamondhub.plugins`` entry point
that resolves to a ``PluginSpec``.
"""
import re
from importlib import import_module
from importlib.metadata import entry_points

from .plugins import API_VERSION, SECTIONS, PluginSpec

ENTRY_POINT_GROUP = "blackdiamondhub.plugins"

# Spec fields holding "module.attribute" paths that are resolved lazily.
DOTTED_FIELDS = ("status", "shortcuts", "run_shortcut", "websocket_routes", "stay")
_DOTTED = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+")


class PluginError(Exception):
    pass


def _import_spec(path: str) -> PluginSpec:
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


def _entry_point_specs():
    return [ep.load() for ep in entry_points(group=ENTRY_POINT_GROUP)]


def validate(specs):
    ids, prefixes = set(), set()
    for spec in specs:
        if not isinstance(spec, PluginSpec):
            raise PluginError(f"{spec!r} is not a PluginSpec")
        if spec.api_version != API_VERSION:
            raise PluginError(
                f"plugin {spec.id!r} targets hub API {spec.api_version}, "
                f"this hub supports {API_VERSION}"
            )
        if spec.id in ids:
            raise PluginError(f"duplicate plugin id {spec.id!r}")
        ids.add(spec.id)
        if spec.urls:
            if spec.prefix in prefixes:
                raise PluginError(f"duplicate URL prefix {spec.prefix!r}")
            prefixes.add(spec.prefix)
        if bool(spec.shortcuts) != bool(spec.run_shortcut):
            raise PluginError(
                f"plugin {spec.id!r} must set both shortcuts and run_shortcut"
            )
        for name in DOTTED_FIELDS:
            value = getattr(spec, name)
            if value is not None and not (
                isinstance(value, str) and _DOTTED.fullmatch(value)
            ):
                raise PluginError(
                    f"plugin {spec.id!r} {name} must be a dotted "
                    f"'module.attribute' path, got {value!r}"
                )
        for tile in spec.tiles:
            if tile.section not in SECTIONS:
                raise PluginError(
                    f"plugin {spec.id!r} tile {tile.title!r} has unknown "
                    f"section {tile.section!r}"
                )
    return specs


def load_plugins(builtin_paths, include_entry_points=True):
    specs = [_import_spec(p) for p in builtin_paths]
    if include_entry_points:
        specs += _entry_point_specs()
    return tuple(validate(specs))


def websocket_urlpatterns(specs=None):
    """Channels URL patterns from every installed plugin, in plugin order.

    Imports each plugin's ``websocket_routes`` module, so call it only once
    Django is set up (the ASGI app does so after ``get_asgi_application()``).
    """
    if specs is None:
        from django.conf import settings

        specs = getattr(settings, "HUB_PLUGINS", ())
    patterns = []
    for spec in specs:
        if spec.websocket_routes:
            patterns.extend(_import_spec(spec.websocket_routes))
    return patterns
