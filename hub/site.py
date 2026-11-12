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
BRAND_FILES = ("monogram", "monogram_light")


def load_site(name=None, sites_dir=SITES_DIR):
    """``{"name", "brand", "location", "features"}`` for the site. Brand file paths come back absolute."""
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
    return {"name": name, "brand": brand, "location": dict(conf.get("location", {})),
            "features": dict(conf.get("features", {}))}