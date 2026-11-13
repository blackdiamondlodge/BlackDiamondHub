"""Per-site config: sites/<site>/site.toml, the brand and the site-only features."""
import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from display.schedule import lodge_minute, window
from hub.context_processors import _brand, brand
from hub.modes import builtin_tiles
from hub.site import SITES_DIR, app_settings, load_site, section_titles
from hub_settings import store as hub_store
from hub_settings.models import AppSetting


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
                         {"name": "bare", "brand": {}, "location": {}, "features": {}, "sections": {},
                          "apps": {}, "events": {}})

    def test_section_titles_default_to_site_neutral_words(self):
        self.assertEqual(section_titles(self.site("bare")["sections"]),
                         {"mountain": "Outside", "lodge": "Inside", "more": "More"})

    def test_site_renames_a_section(self):
        site = self.site("home", '[sections]\nlodge = "In the home"\n')
        self.assertEqual(section_titles(site["sections"])["lodge"], "In the home")

    def test_unknown_or_empty_section_fails(self):
        with self.assertRaisesRegex(ValueError, r"\[sections\] 'garage'"):
            self.site("a", '[sections]\ngarage = "Garage"\n')
        with self.assertRaisesRegex(ValueError, r"\[sections\] 'lodge'"):
            self.site("b", '[sections]\nlodge = " "\n')

    def test_section_ids_match_the_sdk(self):
        from hub.plugins import SECTIONS
        self.assertEqual(list(section_titles({})), list(SECTIONS))

    def test_app_tables_become_namespaced_django_settings(self):
        site = self.site("home", '[apps.sonos_control]\nmodels = "*"\n'
                                 '[apps.sonos_control.rooms]\nKitchen = { icon = "fa-utensils" }\n')
        self.assertEqual(app_settings(site["apps"]), {
            "BDH_SONOS_CONTROL_MODELS": "*",
            "BDH_SONOS_CONTROL_ROOMS": {"Kitchen": {"icon": "fa-utensils"}}})

    def test_app_entry_must_be_a_table(self):
        with self.assertRaisesRegex(ValueError, r"\[apps.wifi\]"):
            self.site("home", '[apps]\nwifi = "x"\n')

    def test_site_app_settings_reach_the_apps(self):
        from bdh_sdk.settings import app_setting
        self.assertEqual(app_setting("sonos_control", "models"), "Amp")
        self.assertEqual([p["id"] for p in app_setting("sonos_control", "presets")], ["dining_deck", "whole"])

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
        response = self.client.get("/")
        self.assertTrue(self.scraped())
        self.assertContains(response, "In the lodge")

    @override_settings(HUB_FEATURES={"mountain_weather": False}, HUB_SECTIONS={"lodge": "In the home"},
                       HUB_BRAND={"name": "Slivinski Hub", "subtitle": "Mercer Island"})
    def test_site_without_it_has_no_tile_and_no_scrape(self):
        self.assertNotIn("weather", [t["kind"] for t in builtin_tiles()])
        response = self.client.get("/")
        self.assertFalse(self.scraped())
        self.assertNotContains(response, "hub-cell hub-wx-tile")
        self.assertContains(response, "<title>Slivinski Hub</title>", html=False)
        self.assertContains(response, "MERCER ISLAND")
        self.assertContains(response, "In the home")
        self.assertNotContains(response, "In the lodge")

    def test_renamed_groups_show_on_home_with_the_weather_heading_its_group(self):
        reading = {"location": "Top", "elevation": 2080, "temperature": "-4"}
        self.enterContext(patch("BlackDiamondHub.views.mountain_weather", return_value=[reading]))
        # Hooks run in threads with their own DB connection, which can't see this
        # test's unsaved layout and would cache the store empty.
        self.enterContext(patch("hub.status.current_stay", return_value=None))
        self.enterContext(patch("BlackDiamondHub.views.lodge_card", return_value=None))
        self.enterContext(patch("BlackDiamondHub.views.home_data", return_value={}))
        hub_store.clear()
        self.addCleanup(hub_store.clear)
        AppSetting.objects.create(app_id="hub", key="home_layout", value={"groups": [
            # Apps the layout doesn't place go to the last group, so the empty one leads.
            {"key": "spare", "title": "Empty now", "tiles": []},
            {"key": "g-out", "title": "Up the hill", "tiles": [{"id": "hub:weather", "size": "l"}]},
        ]})
        response = self.client.get("/")
        self.assertEqual(response.context["hub_weather_key"], "g-out")
        self.assertContains(response, 'id="hub-pane-g-out" data-label="Up the hill"')
        self.assertContains(response, "up top")
        self.assertNotContains(response, "Empty now")


class LocationTests(SimpleTestCase):
    winter = datetime(2027, 1, 15, 20, 0, tzinfo=timezone.utc)
    summer = datetime(2027, 7, 15, 20, 0, tzinfo=timezone.utc)

    def at(self, tz):
        from bdh_sdk.location import Location
        return patch("bdh_sdk.location.location", return_value=Location(timezone=tz) if tz else None)

    def test_follows_the_hub_time_zone(self):
        with self.at("America/Los_Angeles"):
            self.assertEqual(lodge_minute(self.winter), 12 * 60)
            self.assertEqual(lodge_minute(self.summer), 13 * 60)

    def test_night_window_offset_is_the_current_one(self):
        with self.at("America/Los_Angeles"), patch("display.options.value", return_value="23:00"):
            offset = window()["offset"]
        self.assertIn(offset, (-480, -420))

    def test_no_location_means_utc(self):
        with self.at(None):
            self.assertEqual(lodge_minute(self.winter), 20 * 60)
