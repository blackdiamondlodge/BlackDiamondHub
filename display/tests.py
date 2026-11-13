import importlib
import io
import os
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from bdh_sdk.provides import BACKGROUNDS, SEASON, STATS, WINTER, Background, SeasonHint, Stat
from django.apps import apps as django_apps
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from hub.plugins import PluginSpec
from hub_settings import store
from tests.selenium_helpers import SeleniumTestCase, login_via_browser
from . import catalog, views
from hub_settings.models import AppSetting
from .models import SaverPhoto, UploadLink
from .options import DEFAULT_STARTS
from .schedule import is_night, parse_hhmm
from .season import parse_mmdd, resolve
from .stats import collect, days_until_lifts

STARTS = dict(DEFAULT_STARTS)  # winter 11-21, spring 03-15, summer 06-01, fall 09-15


class FakeState(dict):
    def set(self, key, value):
        self[key] = value


class SeasonTests(TestCase):
    def test_by_date(self):
        self.assertEqual(resolve(date(2026, 1, 5), STARTS, use_lifts=False), "winter")
        self.assertEqual(resolve(date(2026, 3, 15), STARTS, use_lifts=False), "spring")
        self.assertEqual(resolve(date(2026, 7, 1), STARTS, use_lifts=False), "summer")
        self.assertEqual(resolve(date(2026, 11, 20), STARTS, use_lifts=False), "fall")
        self.assertEqual(resolve(date(2026, 11, 21), STARTS, use_lifts=False), "winter")

    def test_lifts_bring_winter_forward_inside_window(self):
        state = FakeState()
        self.assertEqual(resolve(date(2026, 11, 1), STARTS, lifts_open=3, state=state), "winter")
        self.assertEqual(state["lifts_opened"], "2026-11-01")

    def test_lifts_ignored_outside_window(self):
        state = FakeState()
        self.assertEqual(resolve(date(2026, 10, 1), STARTS, lifts_open=3, state=state), "fall")
        self.assertNotIn("lifts_opened", state)

    def test_remembered_opening_sticks(self):
        state = FakeState(lifts_opened="2026-11-01")
        self.assertEqual(resolve(date(2026, 11, 5), STARTS, lifts_open=None, state=state), "winter")

    def test_last_years_opening_is_ignored(self):
        state = FakeState(lifts_opened="2025-11-01")
        self.assertEqual(resolve(date(2026, 11, 5), STARTS, lifts_open=0, state=state), "fall")

    def test_lifts_off(self):
        self.assertEqual(resolve(date(2026, 11, 1), STARTS, lifts_open=3, use_lifts=False), "fall")

    def test_parse_mmdd(self):
        self.assertEqual(parse_mmdd("02-29"), (2, 29))
        for bad in ("11/21", "1-21", "13-01", "02-30", "", "abc"):
            with self.assertRaisesMessage(ValueError, "Use MM-DD"):
                parse_mmdd(bad)


class StatTests(TestCase):
    def test_days_until_lifts(self):
        today = date(2026, 11, 11)
        self.assertEqual(days_until_lifts(today, STARTS, False)["value"], "10 days")
        self.assertIsNone(days_until_lifts(today, STARTS, True))
        self.assertIsNone(days_until_lifts(today, STARTS, None))

    @mock.patch("hub.provides.stats", return_value={})
    @mock.patch("hub.provides.stat_owners", return_value=set())
    def test_missing_data_is_skipped(self, _owners, stats):
        # Isolated from the installed apps' providers, which would fetch live data.
        keys = ["snow_report.temp_top", "none", "snow_report.base", "snow_report.wind_top", "lift_status.groomed"]
        self.assertEqual(collect(keys, date(2026, 11, 11), STARTS), [])
        stats.assert_not_called()


P = "display.tests."
PROVIDED = {}


def weather_stats():
    return [Stat("temp", "Outside", value="12°C"), Stat("feels_like", "Feels like", value="10°C"),
            Stat("sun", "Sunset", value="4:30 PM")]


def snow_stats():
    return [Stat("temp_top", "Up top", value="-6°C"), Stat("temp_village", "At the lodge", value="0°C"),
            Stat("snow_48h", "48h snow", value=PROVIDED.get("snow", "20 cm"))]


def lift_stats():
    return [Stat("runs_open", "Runs open", value="112 of 138")]


def webcams():
    return [Background("peak", "Peak cam", "http://cam/peak.jpg", refresh_seconds=30),
            Background("village", "Village cam", "http://cam/village.jpg")]


def lifts_hint():
    return SeasonHint(WINTER, "Lifts are open") if PROVIDED.get("open") else None


_OWN = ("snow_report", "lift_status", "sunpeaks_webcams", "weather")
BASE = tuple(s for s in settings.HUB_PLUGINS if s.id not in _OWN)
SNOW = PluginSpec(id="snow_report", app="snow_report", provides={STATS: P + "snow_stats"},
                  stat_keys=(("temp_top", "Up top"), ("temp_village", "At the lodge"), ("snow_48h", "48h snow")))
LIFTS = PluginSpec(id="lift_status", app="lift_status", provides={STATS: P + "lift_stats"},
                   stat_keys=(("runs_open", "Runs open"),))
CAMS = PluginSpec(id="sunpeaks_webcams", app="sunpeaks_webcams", provides={BACKGROUNDS: P + "webcams"})
MOUNTAIN = BASE + (SNOW, LIFTS, CAMS)
MOUNTAIN_SLOTS = ["snow_report.temp_top", "snow_report.temp_village", "snow_report.snow_48h", "lift_status.runs_open"]
WEATHER = PluginSpec(id="weather", app="weather", provides={STATS: P + "weather_stats"},
                     stat_keys=(("temp", "Outside"), ("feels_like", "Feels like"), ("sun", "Next sunrise or sunset")))
# No site slot defaults: the display's generic ones apply.
NO_SITE_SLOTS = {f"BDH_DISPLAY_SLOTS_{s}": None for s in ("WINTER", "SPRING", "SUMMER", "FALL")}

@override_settings(HUB_PLUGINS=MOUNTAIN, BDH_DISPLAY_SLOTS_WINTER=MOUNTAIN_SLOTS)
class ViewTests(TestCase):
    def setUp(self):
        store.clear()
        cache.clear()
        PROVIDED.clear()
        self.addCleanup(store.clear)
        self.addCleanup(cache.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")

    def test_saver_api(self):
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(body["season"], "winter")
        self.assertEqual(body["sources"], ["stock"])
        self.assertEqual([s["label"] for s in body["stats"]], ["Up top", "At the lodge", "48h snow", "Runs open"])

    def test_saver_api_stock_art(self):
        body = self.client.get(reverse("display_saver_api"), {"season": "fall"}).json()
        self.assertEqual(len(body["stock"]), 8)
        self.assertTrue(all(u.startswith(settings.STATIC_URL + "display/stock/fall/") for u in body["stock"]))
        for season in ("winter", "spring", "summer", "fall"):
            for url in views.stock_art(season):
                self.assertTrue(finders.find(url[len(settings.STATIC_URL):]), url)

    def test_saver_api_cam(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="mix")
        body = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(body["sources"], ["stock", "cam"])
        self.assertEqual(body["cam"], {"name": "Peak cam", "url": "http://cam/peak.jpg",
                                       "timestamp": None, "refresh_seconds": 30})

    def test_saved_cam_picks_that_background(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="cam")
        AppSetting.objects.create(app_id="display", key="cam", value="sunpeaks_webcams.village")
        body = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(body["cam"]["url"], "http://cam/village.jpg")

    def test_site_slot_defaults(self):
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(len(body["stats"]), 4)
        with override_settings(BDH_DISPLAY_SLOTS_WINTER="lift_status.runs_open, snow_report.temp_top"):
            body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual([s["label"] for s in body["stats"]], ["Runs open", "Up top"])
        AppSetting.objects.create(app_id="display", key="slot_winter_1", value="snow_report.snow_48h")
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(body["stats"][0]["label"], "48h snow")
    def test_unavailable_slot_is_kept_and_skipped(self):
        AppSetting.objects.create(app_id="display", key="slot_winter_2", value="ticker.price")
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual([s["label"] for s in body["stats"]], ["Up top", "48h snow", "Runs open"])
        self.client.force_login(self.staff)
        page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<option value="ticker.price" selected>ticker.price (unavailable)</option>')
        self.client.post(reverse("display_settings"), self.form())
        self.assertEqual(store.saved("display")["slot_winter_2"], "ticker.price")

    def test_season_hint_brings_winter_forward(self):
        hint = PluginSpec(id="lift_status", app="lift_status", provides={SEASON: P + "lifts_hint"})
        with override_settings(HUB_PLUGINS=BASE + (hint,)), \
                mock.patch("display.views.lodge_today", return_value=date(2026, 11, 5)):
            self.assertEqual(self.client.get(reverse("display_saver_api")).json()["season"], "fall")
            cache.clear()
            PROVIDED["open"] = True
            self.assertEqual(self.client.get(reverse("display_saver_api")).json()["season"], "winter")

    def test_site_without_mountain_apps(self):
        with override_settings(HUB_PLUGINS=BASE + (WEATHER,), **NO_SITE_SLOTS):
            body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
            self.assertEqual(body["stats"], [{"label": "Outside", "value": "12°C"},
                                             {"label": "Feels like", "value": "10°C"},
                                             {"label": "Sunset", "value": "4:30 PM"}])
            self.client.force_login(self.staff)
            page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<optgroup label="Weather">')
        self.assertNotContains(page, 'name="cam"')
        self.assertNotContains(page, 'id="dsp-lifts"')
        self.assertContains(page, '<input type="hidden" name="winter_on_lifts" value="on">')
        self.assertNotContains(page, 'value="mix"')
        self.assertNotContains(page, "Lift")
        self.assertNotContains(page, "lifts open")

    def test_settings_staff_only(self):
        url = reverse("display_settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_settings_page_and_nav(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("display_settings"))
        self.assertContains(response, "Screensaver, home screen &amp; schedule")
        self.assertContains(response, f'href="{reverse("display_settings")}"')
        self.assertContains(response, 'name="slot_fall_4"')

    def test_generic_app_page_redirects(self):
        self.client.force_login(self.staff)
        response = self.client.get("/settings/app/display/")
        self.assertRedirects(response, reverse("display_settings"), fetch_redirect_response=False)

    def form(self, **overrides):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("display_settings"))
        data = {}
        for s in page.context["seasons"]:
            data[s["start_key"]] = s["start"]
            data[f"source_{s['id']}"] = s["source"]
            data.update({slot["key"]: slot["value"] for slot in s["slots"]})
        data.update(idle_minutes="10", burn_in="on", winter_on_lifts="on", rotate_seconds="180", cam="", tab="fall",
                    night="on", night_from="23:00", night_until="06:00",
                    home_bg="mountains", home_tiles="solid", home_dim="45")
        data.update(overrides)
        return data

    def test_save(self):
        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-1", idle_minutes="15"))
        self.assertEqual(response.status_code, 400)  # 11-1 isn't MM-DD
        self.assertContains(response, "Use MM-DD", status_code=400)
        self.assertContains(response, " data-dirty>", status_code=400)
        page = self.client.get(reverse("display_settings"))
        self.assertContains(page, 'class="hst-btn" data-save>Save')
        self.assertRegex(page.content.decode(), r'id="dsp-tab" value="\w+" data-clean')  # switching tabs isn't a change
        self.assertNotContains(page, " data-dirty>")

        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-01", idle_minutes="15"))
        self.assertRedirects(response, reverse("display_settings") + "?saved=1&season=fall",
                             fetch_redirect_response=False)
        saved = store.saved("display")
        self.assertEqual(saved["winter_start"], "11-01")
        self.assertEqual(saved["idle_minutes"], 15)
        self.assertNotIn("burn_in", saved)  # unchanged defaults stay unsaved
        self.assertNotIn("slot_winter_1", saved)  # so slots follow the site's apps

        self.client.post(reverse("display_settings"), self.form(slot_winter_1="lift_status.groomed"))
        self.assertEqual(store.saved("display")["slot_winter_1"], "lift_status.groomed")
        response = self.client.post(reverse("display_settings"), self.form(slot_winter_1="<b>"))
        self.assertEqual(response.status_code, 400)

    def test_night_times(self):
        response = self.client.post(reverse("display_settings"), self.form(night_from="25:00"))
        self.assertContains(response, "Use HH:MM", status_code=400)

        self.client.post(reverse("display_settings"), self.form(night_from="22:30", night_until="7:00"))
        saved = store.saved("display")
        self.assertEqual((saved["night_from"], saved["night_until"]), ("22:30", "07:00"))

        with mock.patch("display.views.lodge_minute", return_value=23 * 60):
            self.assertTrue(self.client.get(reverse("display_schedule_api")).json()["dark"])
        with mock.patch("display.views.lodge_minute", return_value=12 * 60):
            body = self.client.get(reverse("display_schedule_api")).json()
        self.assertEqual(body, {"enabled": True, "from": "22:30", "until": "07:00", "dark": False})

        self.client.post(reverse("display_settings"), {k: v for k, v in self.form().items() if k != "night"})
        body = self.client.get(reverse("display_schedule_api")).json()
        self.assertEqual(body, {"enabled": False, "from": None, "until": None, "dark": False})

    def home(self):
        # Hook threads (this test's or ones left over from earlier tests) use their own
        # DB connection, can't see this test's uncommitted settings and cache them
        # empty; a zero TTL makes the page read through this test's connection.
        empty = {"status": {}, "shortcuts": [], "refreshing": False}
        with mock.patch("BlackDiamondHub.views.mountain_weather", return_value=[]), \
                mock.patch("BlackDiamondHub.views.home_data", return_value=empty), \
                mock.patch("BlackDiamondHub.views.lodge_card", return_value=None), \
                mock.patch.object(store, "TTL", 0):
            return self.client.get(reverse("landing_page"))

    def test_home_theme_settings(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<input type="radio" name="home_bg" value="mountains" checked>')
        self.assertContains(page, '<input type="radio" name="home_tiles" value="solid" checked>')
        self.assertContains(page, 'name="home_dim" min="0" max="80" step="5" value="45"')

        for bad in ({"home_tiles": "neon"}, {"home_bg": "video"}, {"home_dim": "90"}):
            self.assertEqual(self.client.post(reverse("display_settings"), self.form(**bad)).status_code, 400, bad)
        self.client.post(reverse("display_settings"), self.form(home_bg="art", home_tiles="frosted", home_dim="60"))
        saved = store.saved("display")
        self.assertEqual((saved["home_bg"], saved["home_tiles"], saved["home_dim"]), ("art", "frosted", 60))
        page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<input type="radio" name="home_tiles" value="frosted" checked>')

    @override_settings(BDH_HUB_UNITS="metric")
    def test_units_follow_hub_setting(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<input type="radio" name="units" value="metric" checked>')
        self.assertContains(self.home(), 'data-unit="C"')

        with mock.patch("hub.status.forget_units") as forget, mock.patch.object(store, "TTL", 0):
            self.client.post(reverse("display_settings"), self.form(units="imperial"))
            self.client.post(reverse("display_settings"), self.form(units="imperial"))
            self.client.post(reverse("display_settings"), self.form(units="kelvin"))
        self.assertEqual(forget.call_count, 1)
        self.assertEqual(AppSetting.objects.get(app_id="hub", key="units").value, "imperial")
        with mock.patch.object(store, "TTL", 0):
            page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<input type="radio" name="units" value="imperial" checked>')
        self.assertContains(self.home(), 'data-unit="F"')

    def test_home_weather_text_in_hub_units(self):
        from BlackDiamondHub.views import _with_units
        from bdh_sdk.units import Units
        rows = [{"temperature": "-5", "elevation": 2080}, {"temperature": "N/A", "elevation": "?"}]
        self.assertEqual([(r["temp_text"], r["elev_text"]) for r in _with_units(rows, Units("imperial"))],
                         [("23°F", "6,824 ft"), ("N/A°C", "? m")])
        self.assertEqual(_with_units(rows, Units("metric"))[0]["temp_text"], "-5°C")

    def test_home_defaults_unchanged(self):
        page = self.home()
        self.assertContains(page, 'class="hub-home mode-')
        self.assertContains(page, " tiles-solid\">")
        self.assertNotContains(page, 'id="hub-bg"')
        self.assertContains(page, 'id="hub-sky"')

    def test_home_seasonal_art_and_glass(self):
        AppSetting.objects.create(app_id="display", key="home_bg", value="art")
        AppSetting.objects.create(app_id="display", key="home_tiles", value="dark")
        AppSetting.objects.create(app_id="display", key="home_dim", value=30)
        today = date(2026, 1, 10)
        with mock.patch("display.views.lodge_today", return_value=today), \
                mock.patch("display.views.current_season_safe", return_value="winter"):
            page = self.home()
        art = views.stock_art("winter")
        self.assertContains(page, " tiles-dark has-bg")
        self.assertContains(page, f"--dim: 0.30; background-image: url('{art[today.toordinal() % len(art)]}')")

    def test_home_photos_fall_back_to_art(self):
        AppSetting.objects.create(app_id="display", key="home_bg", value="photos")
        with mock.patch("display.views.current_season_safe", return_value="summer"), \
                mock.patch.object(store, "TTL", 0):
            theme = views.home_theme(date(2026, 7, 1))
            self.assertIn(theme["bg"], views.stock_art("summer"))
            with mock.patch("display.views.season_photos", return_value=[{"url": "/media/a.jpg", "caption": ""}]):
                self.assertEqual(views.home_theme(date(2026, 7, 1))["bg"], "/media/a.jpg")

    def test_settings_previews_each_home_background(self):
        AppSetting.objects.create(app_id="display", key="home_tiles", value="frosted")
        self.client.force_login(self.staff)
        with mock.patch("display.views.current_season_safe", return_value="summer"), \
                mock.patch("display.views.season_photos", return_value=[{"url": "/media/a.jpg", "caption": ""}]), \
                mock.patch.object(store, "TTL", 0):
            page = self.client.get(reverse("display_settings"))
        self.assertContains(page, '<div class="dsp-mini tiles-frosted" id="dsp-mini"')
        pics = page.context["home_pictures"]
        self.assertEqual(pics["mountains"], None)
        self.assertIn(pics["art"], views.stock_art("summer"))
        self.assertEqual(pics["photos"], "/media/a.jpg")
        self.assertContains(page, 'id="dsp-home-pics"')

    def test_home_preview_never_breaks_settings(self):
        self.client.force_login(self.staff)
        with mock.patch("display.views.home_picture", side_effect=RuntimeError), \
                mock.patch.object(store, "TTL", 0):
            page = self.client.get(reverse("display_settings"))
        self.assertEqual(page.context["home_pictures"], {})

    def test_home_theme_never_breaks_home(self):
        AppSetting.objects.create(app_id="display", key="home_bg", value="art")
        with mock.patch("display.views.stock_art", side_effect=RuntimeError), \
                mock.patch.object(store, "TTL", 0):
            self.assertEqual(views.home_theme(), views.HOME_DEFAULT)
            self.assertEqual(self.home().status_code, 200)


class RotateMigrationTests(TestCase):
    """0003 turns the old "Change every" minutes into seconds within 30 s - 10 min."""

    def test_to_seconds(self):
        mig = importlib.import_module("display.migrations.0003_rotate_seconds")
        self.assertEqual([mig.to_seconds(v) for v in (3, "2", 60, 0, "x", None)], [180, 120, 600, 30, None, None])

    def test_forwards_moves_saved_value(self):
        mig = importlib.import_module("display.migrations.0003_rotate_seconds")
        AppSetting.objects.create(app_id="display", key="rotate_minutes", value=5)
        AppSetting.objects.create(app_id="other", key="rotate_minutes", value=5)
        mig.forwards(django_apps, None)
        self.assertEqual(AppSetting.objects.get(app_id="display", key="rotate_seconds").value, 300)
        self.assertFalse(AppSetting.objects.filter(app_id="display", key="rotate_minutes").exists())
        self.assertTrue(AppSetting.objects.filter(app_id="other", key="rotate_minutes").exists())
        mig.backwards(django_apps, None)
        self.assertEqual(AppSetting.objects.get(app_id="display", key="rotate_minutes").value, 5)
        self.assertFalse(AppSetting.objects.filter(key="rotate_seconds").exists())


class CatalogTests(TestCase):
    def test_groups(self):
        with override_settings(HUB_PLUGINS=BASE + (WEATHER,)):
            self.assertEqual(catalog.stat_groups(["weather.temp", "gone.x"]), [
                ("Weather", [("weather.temp", "Outside"), ("weather.feels_like", "Feels like"),
                             ("weather.sun", "Next sunrise or sunset")]),
                ("Unavailable", [("gone.x", "gone.x (unavailable)")]),
            ])
        with override_settings(HUB_PLUGINS=MOUNTAIN):
            groups = dict(catalog.stat_groups())
        self.assertIn(("lift_status.runs_open", "Runs open"), groups["Lift Status"])
        self.assertNotIn("Screensaver", groups)  # days until lifts needs an app that knows the season
        hint = PluginSpec(id="lift_status", app="lift_status", provides={STATS: P + "lift_stats", SEASON: P + "lifts_hint"},
                          stat_keys=(("runs_open", "Runs open"),))
        with override_settings(HUB_PLUGINS=BASE + (SNOW, hint)):
            groups = dict(catalog.stat_groups())
        self.assertEqual(groups["Screensaver"], [("days_until_lifts", "Days until lifts open")])


class ScheduleTests(TestCase):
    def test_is_night_wraps_midnight(self):
        night = (23 * 60, 6 * 60)
        self.assertTrue(is_night(23 * 60, *night))
        self.assertTrue(is_night(3 * 60, *night))
        self.assertFalse(is_night(6 * 60, *night))
        self.assertFalse(is_night(12 * 60, *night))
        self.assertTrue(is_night(14 * 60, 13 * 60, 15 * 60))
        self.assertFalse(is_night(0, 0, 0))  # same start and end: never

    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm(" 6:05 "), 365)
        for bad in ("", "6", "24:00", "12:60", "ab:cd"):
            with self.assertRaises(ValueError):
                parse_hhmm(bad)


def jpeg(size=(800, 600), orientation=None, name="p.jpg", taken=None):
    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    exif = img.getexif()
    if orientation:
        exif[0x0112] = orientation
    if taken:
        exif[0x8769] = {36867: taken}  # Exif IFD: DateTimeOriginal
    exif[0x010F] = "SecretCam"  # Make: must not survive processing
    img.save(buf, "JPEG", exif=exif)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(HUB_PLUGINS=BASE)  # no live providers
class PhotoTests(TestCase):
    def setUp(self):
        self.addCleanup(store.clear)
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        storage = FileSystemStorage(root, base_url="/media/apps/display/")
        for name in ("image", "thumb"):
            patcher = mock.patch.object(SaverPhoto._meta.get_field(name), "storage", storage)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = root
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")
        self.client.force_login(self.staff)

    def link(self):
        return self.client.post(reverse("display_upload_link")).json()

    def test_phone_upload_flow(self):
        link = self.link()
        self.assertIn("<svg", link["qr"])
        self.assertTrue(link["url"].endswith(f"/display/upload/{link['key']}/"))
        phone = Client()
        page = phone.get(reverse("display_upload", args=[link["key"]]))
        self.assertContains(page, "Choose photos")
        self.assertEqual(page["Cache-Control"], "no-store")
        response = phone.post(reverse("display_upload_photo", args=[link["key"]]),
                              {"photo": jpeg(), "seasons": "summer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["photos"][0]["tag"], "Summer")
        status = self.client.get(reverse("display_photos"), {"link": link["key"]}).json()
        self.assertEqual(status["link"]["arrived"], 1)
        self.assertTrue(status["link"]["claimed"])
        self.assertGreater(status["link"]["seconds"], 25 * 60)  # claiming extends the code

        other = Client()
        self.assertEqual(other.get(reverse("display_upload", args=[link["key"]])).status_code, 403)
        self.assertEqual(other.post(reverse("display_upload_photo", args=[link["key"]]),
                                    {"photo": jpeg()}).status_code, 403)

    def test_upload_link_errors(self):
        phone = Client()
        self.assertEqual(phone.get(reverse("display_upload", args=["nope"])).status_code, 404)
        link = UploadLink.objects.create()
        # Posting without opening the page (no claim) is refused.
        self.assertEqual(phone.post(reverse("display_upload_photo", args=[link.key]),
                                    {"photo": jpeg()}).status_code, 403)
        UploadLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(phone.get(reverse("display_upload", args=[link.key])), "expired", status_code=410)

    def test_processing(self):
        response = self.client.post(reverse("display_photo_add"), {"photo": jpeg((4000, 1000), orientation=6)})
        self.assertEqual(response.status_code, 200)
        photo = SaverPhoto.objects.get()
        self.assertEqual(photo.seasons, [])
        with Image.open(photo.image.path) as img:
            self.assertEqual(img.size, (640, 2560))  # rotated upright, then fit to 2560
            self.assertNotIn(0x010F, img.getexif())
        with Image.open(photo.thumb.path) as img:
            self.assertLessEqual(max(img.size), 480)

        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        self.assertEqual(self.client.post(reverse("display_photo_add"), {"photo": bad}).status_code, 400)

    def test_update_and_delete(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(), "seasons": "winter,spring,summer,fall"})
        photo = SaverPhoto.objects.get()
        self.assertEqual(photo.seasons, [])  # all four means any season
        url = reverse("display_photo_update", args=[photo.id])
        body = self.client.post(url, {"seasons": "fall,winter", "enabled": "0"}).json()
        self.assertEqual(body["seasons"], ["fall", "winter"])
        self.assertFalse(body["enabled"])
        path = photo.image.path
        self.client.post(reverse("display_photo_delete", args=[photo.id]))
        self.assertFalse(SaverPhoto.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_staff_only(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg()})
        photo = SaverPhoto.objects.get()
        self.client.force_login(self.guest)
        for url in (reverse("display_upload_link"), reverse("display_photo_add"),
                    reverse("display_photo_update", args=[photo.id]),
                    reverse("display_photo_delete", args=[photo.id])):
            self.assertEqual(self.client.post(url, {"enabled": "0"}).status_code, 302, url)
        self.assertEqual(self.client.get(reverse("display_photos")).status_code, 302)
        self.assertTrue(SaverPhoto.objects.get().enabled)

    def test_saver_api_photos(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        AppSetting.objects.create(app_id="display", key="source_winter", value="photos")
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(), "seasons": "summer"})
        summer = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(summer["sources"], ["photos"])
        self.assertEqual(summer["photos"], [{"url": SaverPhoto.objects.get().image.url, "caption": ""}])
        winter = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(winter["sources"], ["stock"])  # no winter photos: fall back to the scene
        SaverPhoto.objects.update(enabled=False)
        summer = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(summer["sources"], ["stock"])

    def test_caption_from_exif_date(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(taken="2024:03:31 23:30:00")})
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(name="q.jpg")})
        dated = SaverPhoto.objects.exclude(taken_at=None).get()
        self.assertEqual((dated.taken_at.year, dated.taken_at.month, dated.taken_at.day), (2024, 3, 31))
        api = reverse("display_saver_api")
        off = self.client.get(api, {"season": "summer"}).json()["photos"]
        self.assertEqual({p["caption"] for p in off}, {""})
        AppSetting.objects.create(app_id="display", key="photo_caption", value=True)
        store.clear()
        on = self.client.get(api, {"season": "summer"}).json()["photos"]
        self.assertEqual(sorted(p["caption"] for p in on), ["", "March 2024"])

    def test_preview_overrides_are_staff_only(self):
        self.client.post(reverse("display_photo_add"), {"photo": jpeg(taken="2023:12:25 08:00:00")})
        api = reverse("display_saver_api")
        preview = {"season": "summer", "source": "photos", "rotate": "9999", "caption": "1"}
        body = self.client.get(api, preview).json()
        self.assertEqual(body["sources"], ["photos"])
        self.assertEqual(body["rotate_seconds"], 600)  # clamped to the slider's range
        self.assertEqual(self.client.get(api, dict(preview, rotate="5")).json()["rotate_seconds"], 30)
        self.assertEqual(body["photos"][0]["caption"], "December 2023")
        self.client.force_login(self.guest)
        body = self.client.get(api, preview).json()
        self.assertEqual(body["sources"], ["stock"])
        self.assertEqual(body["photos"], [])

@tag("selenium")
@override_settings(HUB_PLUGINS=BASE)
class SaverBrokenPhotoSeleniumTest(SeleniumTestCase):
    """A photo that fails to load must not leave the screensaver black (regression)."""

    GOOD = "android-chrome-512x512.png"  # a real file in static/, served by the live server

    def setUp(self):
        super().setUp()
        self.addCleanup(store.clear)
        storage = FileSystemStorage(os.path.join(settings.BASE_DIR, "static"), base_url=settings.STATIC_URL)
        for name in ("image", "thumb"):
            patcher = mock.patch.object(SaverPhoto._meta.get_field(name), "storage", storage)
            patcher.start()
            self.addCleanup(patcher.stop)
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        self.browser.get("about:blank")

    def add(self, name):
        SaverPhoto.objects.create(image=name, thumb=name)

    def open_saver(self):
        self.browser.get(self.live_server_url + "/?saver=1&saver_season=summer")

    def layer(self, name):
        return self.browser.find_element(By.CSS_SELECTOR, f".bdh-saver .layer.{name}")

    def test_only_broken_photos_fall_back_to_stock(self):
        self.add("missing-1.jpg")
        self.add("missing-2.jpg")
        self.open_saver()
        WebDriverWait(self.browser, 20).until(lambda d: "on" in self.layer("stock").get_attribute("class"))
        self.assertNotIn("on", self.layer("photos").get_attribute("class"))

    def test_stock_rotates_season_paintings(self):
        self.open_saver()  # no photos yet: the stock layer shows
        frame = (By.CSS_SELECTOR, ".bdh-saver .layer.stock.on .frame.in")
        WebDriverWait(self.browser, 20).until(EC.presence_of_element_located(frame))
        self.assertIn("/display/stock/summer/", self.browser.find_element(*frame).get_attribute("data-src"))
        self.assertTrue(self.browser.find_elements(By.CSS_SELECTOR, ".bdh-saver .layer.stock > svg"))

    def test_broken_photos_are_skipped(self):
        for n in range(3):
            self.add(f"missing-{n}.jpg")
        self.add(self.GOOD)
        self.open_saver()
        frame = (By.CSS_SELECTOR, ".bdh-saver .layer.photos.on .frame")
        WebDriverWait(self.browser, 20).until(EC.presence_of_element_located(frame))
        self.assertTrue(self.browser.find_element(*frame).get_attribute("data-src").endswith(self.GOOD))


@tag("selenium")
@override_settings(HUB_PLUGINS=BASE)
class DisplaySettingsSeleniumTest(SeleniumTestCase):
    """Settings → Display in a real browser (regressions)."""

    GOOD = "android-chrome-512x512.png"

    def setUp(self):
        super().setUp()
        self.addCleanup(store.clear)
        storage = FileSystemStorage(os.path.join(settings.BASE_DIR, "static"), base_url=settings.STATIC_URL)
        for name in ("image", "thumb"):
            patcher = mock.patch.object(SaverPhoto._meta.get_field(name), "storage", storage)
            patcher.start()
            self.addCleanup(patcher.stop)
        get_user_model().objects.create_superuser("testuser", "t@example.com", "testpassword")
        login_via_browser(self.browser, self.live_server_url)

    def open(self):
        self.browser.get(self.live_server_url + reverse("display_settings") + "?season=summer")
        WebDriverWait(self.browser, 20).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#dsp-prev img"))

    def preview_src(self):
        return self.browser.find_element(By.CSS_SELECTOR, "#dsp-prev img").get_attribute("src")

    def test_my_photos_preview_shows_a_library_photo(self):
        SaverPhoto.objects.create(image=self.GOOD, thumb=self.GOOD)
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        self.open()
        self.assertTrue(self.preview_src().endswith(self.GOOD))
        self.browser.find_element(By.CSS_SELECTOR, 'input[name="source_summer"][value="stock"]').click()
        WebDriverWait(self.browser, 5).until(lambda d: "/display/stock/summer/" in self.preview_src())
        self.browser.find_element(By.CSS_SELECTOR, 'input[name="source_summer"][value="photos"]').click()
        WebDriverWait(self.browser, 5).until(lambda d: self.preview_src().endswith(self.GOOD))

    def test_my_photos_preview_falls_back_to_paintings(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="photos")
        self.open()
        self.assertIn("/display/stock/summer/", self.preview_src())

    def test_no_scrollbar_and_a_scroll_hint(self):
        self.browser.set_window_size(1280, 800)
        self.open()
        b = self.browser
        scrollers = "[document.documentElement, document.body]"
        self.assertTrue(b.execute_script(f"return {scrollers}.some(e => e.scrollHeight > e.clientHeight)"))
        self.assertEqual(b.execute_script(f"return {scrollers}.map(e => e.offsetWidth - e.clientWidth)"), [0, 0])
        hint = b.find_element(By.ID, "hst-more")
        WebDriverWait(b, 5).until(lambda d: "hidden" not in hint.get_attribute("class"))
        b.execute_script(f"{scrollers}.forEach(e => e.scrollTop = e.scrollHeight)")
        WebDriverWait(b, 5).until(lambda d: "hidden" in hint.get_attribute("class"))