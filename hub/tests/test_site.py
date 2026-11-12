"""Per-site config: sites/<site>/site.toml, the brand and the site-only features."""
import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from display.schedule import lodge_minute, window
from display.stats import stat
from hub.context_processors import _brand, brand
from hub.modes import builtin_tiles
from hub.site import SITES_DIR, load_site


class LoadSiteTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def site(self, name, toml=None, files=()):
        folder = self.dir / name
        folder.mkdir()
        if toml is not None:
            (folder / "site.toml").write_text(toml, encoding="utf-8")
        for f in files:
            (folder / f).parent.mkdir(parents=True, exist_ok=True)
            (folder / f).write_text("<svg/>", encoding="utf-8")
        return load_site(name, sites_dir=self.dir)

    def test_missing_site_folder_fails(self):
        with self.assertRaisesRegex(ValueError, "nowhere"):
            load_site("nowhere", sites_dir=self.dir)

    def test_site_without_toml_gets_empty_sections(self):
        self.assertEqual(self.site("bare"),
                         {"name": "bare", "brand": {}, "location": {}, "features": {}})

    def test_brand_files_resolve_inside_the_site_folder(self):
        site = self.site("home", '[brand]\nname = "Home"\nmonogram = "brand/m.svg"\n', ["brand/m.svg"])
        self.assertEqual(site["brand"]["name"], "Home")
        self.assertEqual(Path(site["brand"]["monogram"]), self.dir / "home" / "brand" / "m.svg")

    def test_missing_brand_file_fails(self):
        with self.assertRaisesRegex(ValueError, "monogram_light"):
            self.site("home", '[brand]\nmonogram_light = "gone.svg"\n')

    def test_every_shipped_site_loads(self):
        for folder in SITES_DIR.iterdir():
            site = load_site(folder.name)
            self.assertTrue(site["brand"].get("name"), folder.name)
            self.assertTrue(site["location"].get("timezone"), folder.name)


class BrandTests(SimpleTestCase):
    def setUp(self):
        _brand.cache_clear()
        self.addCleanup(_brand.cache_clear)

    def hub_brand(self):
        return brand(RequestFactory().get("/"))["hub_brand"]

    def test_sun_peaks_brand_and_its_own_monogram(self):
        b = self.hub_brand()
        self.assertEqual((b["name"], b["subtitle"]), ("Black Diamond Lodge", "Sun Peaks · BC"))
        svg = base64.b64decode(b["monogram_light"].split(",", 1)[1]).decode()
        self.assertEqual(svg, (SITES_DIR / "sunpeaks/brand/bdl-monogram-light.svg").read_text(encoding="utf-8"))

    @override_settings(HUB_BRAND={})
    def test_site_without_a_brand_gets_the_bdh_default(self):
        b = self.hub_brand()
        self.assertEqual(b["name"], "Black Diamond Hub")
        self.assertTrue(b["monogram"].startswith("data:image/svg+xml;base64,"))
        self.assertIn('aria-label="Black Diamond Hub"', base64.b64decode(b["monogram"].split(",", 1)[1]).decode())


class OgImageTests(SimpleTestCase):
    def setUp(self):
        _brand.cache_clear()
        self.addCleanup(_brand.cache_clear)

    @override_settings(ALLOWED_HOSTS=["hub.example"])
    def test_pages_advertise_the_sites_preview_card(self):
        response = self.client.get("/accounts/login/", HTTP_HOST="hub.example:8000")
        self.assertContains(response, '<meta property="og:image" content="http://hub.example:8000/og-image.png">', html=False)
        self.assertContains(response, '<meta property="og:title" content="Black Diamond Lodge">', html=False)
        image = self.client.get("/og-image.png", HTTP_HOST="hub.example:8000")
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertEqual(b"".join(image.streaming_content),
                         (SITES_DIR / "sunpeaks/brand/og-image.png").read_bytes())

    @override_settings(HUB_BRAND={})
    def test_site_without_a_card_has_no_og_image(self):
        self.assertNotContains(self.client.get("/accounts/login/"), "og:image")
        self.assertEqual(self.client.get("/og-image.png").status_code, 404)


class MountainWeatherTests(TestCase):
    def setUp(self):
        _brand.cache_clear()
        self.addCleanup(_brand.cache_clear)
        patcher = patch("BlackDiamondHub.views.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)
        self.get.return_value = MagicMock(status_code=200, content=b"")

    def scraped(self):
        return any("weather-webcams/weather" in str(c.args[:1]) for c in self.get.call_args_list)

    def test_sun_peaks_has_the_weather_tile(self):
        self.assertIn("weather", [t["kind"] for t in builtin_tiles()])
        self.client.get("/")
        self.assertTrue(self.scraped())

    @override_settings(HUB_FEATURES={"mountain_weather": False},
                       HUB_BRAND={"name": "Slivinski Hub", "subtitle": "Mercer Island"})
    def test_site_without_it_has_no_tile_and_no_scrape(self):
        self.assertNotIn("weather", [t["kind"] for t in builtin_tiles()])
        response = self.client.get("/")
        self.assertFalse(self.scraped())
        self.assertNotContains(response, "hub-cell hub-wx-tile")
        self.assertContains(response, "<title>Slivinski Hub</title>", html=False)
        self.assertContains(response, "MERCER ISLAND")


class LocationTests(SimpleTestCase):
    winter = datetime(2027, 1, 15, 20, 0, tzinfo=timezone.utc)
    summer = datetime(2027, 7, 15, 20, 0, tzinfo=timezone.utc)

    def test_sun_peaks_is_utc_minus_7_all_year(self):
        self.assertEqual(lodge_minute(self.winter), 13 * 60)
        self.assertEqual(lodge_minute(self.summer), 13 * 60)

    @override_settings(HUB_LOCATION={"timezone": "America/Los_Angeles"})
    def test_other_sites_follow_their_time_zone(self):
        self.assertEqual(lodge_minute(self.winter), 12 * 60)
        self.assertEqual(lodge_minute(self.summer), 13 * 60)

    @override_settings(HUB_LOCATION={"timezone": "America/Los_Angeles"})
    def test_night_window_offset_is_the_current_one(self):
        with patch("display.options.value", return_value="23:00"):
            offset = window()["offset"]
        self.assertIn(offset, (-480, -420))

    @override_settings(HUB_LOCATION={})
    def test_no_location_means_utc_and_no_sun_times(self):
        self.assertEqual(lodge_minute(self.winter), 20 * 60)
        self.assertIsNone(stat("sunrise", {}, self.winter.date(), {}))
