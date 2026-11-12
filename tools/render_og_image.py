"""Render a site's link-preview card (og:image) to sites/<site>/brand/og-image.png.

Link previews (UniFi Connect's dashboard thumbnail, chat apps) need a raster
image, so the card is drawn from the site's brand with headless Edge/Chrome:

    python tools/render_og_image.py <site> [--browser PATH]

Then set ``og_image = "brand/og-image.png"`` in the site's site.toml.
"""
import argparse
import base64
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.site import SITES_DIR, load_site  # noqa: E402

WIDTH, HEIGHT = 1200, 630
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "msedge", "google-chrome", "chromium", "chromium-browser",
)

CARD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; }}
body {{ display: flex; align-items: center; gap: 64px; padding: 0 96px; box-sizing: border-box;
  background: radial-gradient(circle at 25% 40%, #1d2b45 0, #121c2c 45%, #0d1420 100%);
  font-family: "Segoe UI", system-ui, sans-serif; color: #eef3fa; }}
img {{ width: 300px; height: 300px; flex: none; filter: drop-shadow(0 0 40px rgba(91,164,230,.35)); }}
h1 {{ margin: 0; font-size: 84px; font-weight: 600; line-height: 1.05; }}
p {{ margin: 20px 0 0; font-size: 40px; letter-spacing: .12em; text-transform: uppercase; color: #8fa3bd; }}
</style></head><body><img src="{img}"><div><h1>{name}</h1><p>{subtitle}</p></div></body></html>"""


def card_html(site):
    from bdh_sdk.branding import DEFAULT_NAME, _DEFAULTS

    brand = site["brand"]
    svg = Path(brand.get("monogram_light") or _DEFAULTS["monogram_light"]).read_bytes()
    return CARD.format(
        w=WIDTH, h=HEIGHT,
        img="data:image/svg+xml;base64," + base64.b64encode(svg).decode(),
        name=html.escape(brand.get("name") or DEFAULT_NAME),
        subtitle=html.escape(brand.get("subtitle") or ""),
    )


def find_browser(explicit):
    for candidate in ([explicit] if explicit else BROWSERS):
        path = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if path:
            return path
    sys.exit("No Edge/Chrome found; pass --browser")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site")
    parser.add_argument("--browser")
    args = parser.parse_args()

    site = load_site(args.site)
    out = SITES_DIR / args.site / "brand" / "og-image.png"
    out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "card.html"
        page.write_text(card_html(site), encoding="utf-8")
        subprocess.run([
            find_browser(args.browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={Path(tmp) / 'profile'}", f"--window-size={WIDTH},{HEIGHT}",
            f"--screenshot={out}", page.as_uri(),
        ], check=True, capture_output=True, timeout=60)
    print(out)


if __name__ == "__main__":
    main()
