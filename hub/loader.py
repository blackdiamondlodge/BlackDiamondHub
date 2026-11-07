"""Discovers and validates hub plugins.

Built-in apps are listed explicitly by dotted path to their ``spec``.
Separately installed apps register a ``blackdiamondhub.plugins`` entry point
that resolves to a ``PluginSpec``.
"""
from importlib import import_module
from importlib.metadata import entry_points

from .plugins import API_VERSION, SECTIONS, PluginSpec

ENTRY_POINT_GROUP = "blackdiamondhub.plugins"


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
