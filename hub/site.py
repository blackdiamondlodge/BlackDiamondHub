"""The site this hub serves, from ``sites/<HUB_SITE>/site.toml``.

A site folder holds everything that differs between deployments: the apps
installed into its image (``apps.txt``), its brand and which built-in
features it has. ``HUB_SITE`` is baked into each site's image.
"""
import os
import tomllib
from pathlib import Path

SITES_DIR = Path(__file__).resolve().parent.parent / "sites"
DEFAULT_SITE = "sunpeaks"
BRAND_FILES = ("monogram", "monogram_light", "og_image")
# Homepage section titles unless the site's [sections] table renames them.
# The keys are the bdh_sdk section ids apps put their tiles in.
SECTION_TITLES = {"mountain": "Outside", "lodge": "Inside", "more": "More"}


def section_titles(sections=None):
    """``{section_id: title}``, the site's titles over the defaults, in display order."""
    if sections is None:
        from django.conf import settings
        sections = getattr(settings, "HUB_SECTIONS", {})
    return {key: sections.get(key, title) for key, title in SECTION_TITLES.items()}


def load_site(name=None, sites_dir=SITES_DIR):
    """``{"name", "brand", "location", "features", "apps"}`` for the site. Brand file paths come back absolute.

    ``apps`` is ``{app_id: {key: value}}`` from the ``[apps.<app_id>]`` tables:
    per-site settings for installed apps (see :func:`app_settings`).
    """
    name = name or os.getenv("HUB_SITE") or DEFAULT_SITE
    folder = Path(sites_dir) / name
    if not folder.is_dir():
        raise ValueError(f"HUB_SITE={name!r}: no folder {folder}")
    path = folder / "site.toml"
    conf = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    brand = dict(conf.get("brand", {}))
    for key in BRAND_FILES:
        if brand.get(key):
            brand[key] = str(folder / brand[key])
            if not Path(brand[key]).is_file():
                raise ValueError(f"site {name!r}: brand {key} file {brand[key]} not found")
    apps = conf.get("apps", {})
    for app_id, values in apps.items():
        if not isinstance(values, dict):
            raise ValueError(f"site {name!r}: [apps.{app_id}] must be a table")
    sections = dict(conf.get("sections", {}))
    for key, title in sections.items():
        if key not in SECTION_TITLES or not isinstance(title, str) or not title.strip():
            raise ValueError(f"site {name!r}: [sections] {key!r} must be one of "
                             f"{', '.join(SECTION_TITLES)} with a title")
    return {"name": name, "brand": brand,
            "features": dict(conf.get("features", {})), "sections": sections,
            "apps": {app_id: dict(values) for app_id, values in apps.items()},
            "events": event_sources(name, conf.get("events", {}).get("sources", {}))}


def event_sources(site, sources):
    """Validated ``[events.sources.<name>]`` tables (see ``hub/events.py``)."""
    from .events import TYPES

    out = {}
    for source, conf in sources.items():
        where = f"site {site!r}: [events.sources.{source}]"
        if not isinstance(conf, dict):
            raise ValueError(f"{where} must be a table")
        if not source or any(c in source for c in "/+#"):
            raise ValueError(f"{where}: bad source name")
        if conf.get("type") not in TYPES:
            raise ValueError(f"{where}: type must be one of {', '.join(TYPES)}")
        if conf["type"] == "webhook" and not conf.get("secret_env"):
            raise ValueError(f"{where}: webhook needs secret_env")
        out[source] = dict(conf)
    return out


def app_settings(apps):
    """Django settings for the site's app config: ``{"BDH_<APP>_<KEY>": value}``.

    Apps read them with ``bdh_sdk.settings.app_setting``, after the Settings
    page and the environment.
    """
    from bdh_sdk.settings import setting_name
    return {setting_name(app_id, key): value
            for app_id, values in apps.items() for key, value in values.items()}