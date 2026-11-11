from datetime import date
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from hub_settings import store
from hub_settings.models import AppSetting
from .options import DEFAULT_STARTS
from .season import parse_mmdd, resolve
from .stats import MINUS, collect, stat, sun_times

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


DATA = {
    "resort": {
        "temperatures": [
            {"name": "Top of the World", "elevation_m": 2080, "c": -6.4},
            {"name": "Valley", "elevation_m": 1255, "c": 0.4},
        ],
        "new_snow": [{"period": "48 Hr", "cm": 38}],
    },
    "lifts": {"lifts_open": 0, "lifts_total": 13, "trails_open": 112, "trails_total": 138},
}


class StatTests(TestCase):
    def test_formats(self):
        today = date(2026, 11, 11)
        self.assertEqual(stat("temp_top", DATA, today, STARTS), {"label": "Up top", "value": f"{MINUS}6°C"})
        self.assertEqual(stat("temp_village", DATA, today, STARTS)["value"], "0°C")
        self.assertEqual(stat("new_snow", DATA, today, STARTS)["value"], "38 cm")
        self.assertEqual(stat("runs_open", DATA, today, STARTS)["value"], "112 of 138")
        self.assertEqual(stat("days_until_lifts", DATA, today, STARTS)["value"], "10 days")

    def test_missing_data_is_skipped(self):
        keys = ["temp_top", "none", "base", "wind_top", "groomed"]
        self.assertEqual(collect(keys, {}, date(2026, 11, 11), STARTS), [])

    def test_sun_times_are_plausible(self):
        rise, sets = sun_times(date(2026, 6, 21))
        # Sun Peaks summer solstice: about 4:45 and 21:15 local (UTC-7).
        self.assertEqual(((rise.hour - 7) % 24, rise.minute // 15), (4, 3))
        self.assertEqual(((sets.hour - 7) % 24, sets.minute // 15), (21, 1))


@override_settings(HUB_PLUGINS=settings.HUB_PLUGINS)
class ViewTests(TestCase):
    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")
        for target, value in (("display.views.gather", DATA), ("display.views._cams", [
            {"camera_name": "Sunburst Express", "slug": "sunburst", "image_url": "http://x/s.jpg"},
            {"camera_name": "Village", "slug": "village", "image_url": "http://x/v.jpg"},
        ])):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saver_api(self):
        body = self.client.get(reverse("display_saver_api"), {"season": "winter"}).json()
        self.assertEqual(body["season"], "winter")
        self.assertEqual(body["sources"], ["stock"])
        self.assertEqual([s["label"] for s in body["stats"]], ["Up top", "At the lodge", "New snow, 48h", "Runs open"])

    def test_saver_api_cam(self):
        AppSetting.objects.create(app_id="display", key="source_summer", value="mix")
        body = self.client.get(reverse("display_saver_api"), {"season": "summer"}).json()
        self.assertEqual(body["sources"], ["stock", "cam"])
        self.assertEqual(body["cam"]["name"], "Sunburst Express")

    def test_settings_staff_only(self):
        url = reverse("display_settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_settings_page_and_nav(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("display_settings"))
        self.assertContains(response, "Screensaver, background &amp; schedule")
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
        data.update(idle_minutes="10", burn_in="on", winter_on_lifts="on", rotate_minutes="3", cam="", tab="fall")
        data.update(overrides)
        return data

    def test_save(self):
        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-1", idle_minutes="15"))
        self.assertEqual(response.status_code, 400)  # 11-1 isn't MM-DD
        self.assertContains(response, "Use MM-DD", status_code=400)

        response = self.client.post(reverse("display_settings"), self.form(winter_start="11-01", idle_minutes="15"))
        self.assertRedirects(response, reverse("display_settings") + "?saved=1&season=fall",
                             fetch_redirect_response=False)
        saved = store.saved("display")
        self.assertEqual(saved["winter_start"], "11-01")
        self.assertEqual(saved["idle_minutes"], 15)
        self.assertNotIn("burn_in", saved)  # unchanged defaults stay unsaved
