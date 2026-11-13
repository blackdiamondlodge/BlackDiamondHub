import json
from unittest import mock

from bdh_sdk.plugins import BOOL, CHOICE, INT, MULTI, TIME
from bdh_sdk.settings import app_setting
from bdh_sdk.storage import app_state
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from hub.loader import PluginError, validate
from hub.plugins import PluginSpec, Setting, SettingsPage
from hub.tests.test_hub import QUICK_PLUGINS

from . import store
from .models import AppSetting, AppState

DEMO = PluginSpec(
    id="demo",
    app="demo",
    settings=(
        Setting("enabled", "Enabled", type=BOOL, default=True),
        Setting("idle", "Idle after", type=INT, default=5, minimum=1, maximum=60, unit="min"),
        Setting("theme", "Theme", type=CHOICE, default="auto", choices=("auto", "dark")),
        Setting("start", "Starts at", type=TIME, default="23:00"),
        Setting("title", "Title", default="Hello"),
    ),
)
PLUGINS = tuple(settings.HUB_PLUGINS) + (DEMO,)


def _rooms():
    return [("u1", "Kitchen"), ("u2", "Den")]


@override_settings(HUB_PLUGINS=PLUGINS)
class SettingsPageTests(TestCase):
    url = "/settings/app/demo/"

    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")

    def post(self, **overrides):
        data = {"enabled": "on", "idle": "5", "theme": "auto", "start": "23:00", "title": "Hello"}
        data.update(overrides)
        return self.client.post(self.url, {k: v for k, v in data.items() if v is not None})

    def test_staff_only(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(reverse("hub_settings_apps")).status_code, 302)

    def test_lists_apps_with_settings(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("hub_settings"), follow=True)
        self.assertContains(response, 'href="/settings/app/demo/"')
        self.assertContains(response, "Feedback")

    def test_unknown_app_is_404(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/settings/app/feedback/").status_code, 404)

    def test_unchanged_defaults_are_not_saved(self):
        self.client.force_login(self.staff)
        self.assertRedirects(self.post(), self.url + "?saved=1")
        self.assertFalse(AppSetting.objects.exists())

    def test_save_overrides_app_setting(self):
        self.client.force_login(self.staff)
        self.post(enabled=None, idle="15", theme="dark", start="22:30")
        self.assertEqual(app_setting("demo", "enabled", True), False)
        self.assertEqual(app_setting("demo", "idle", 5), 15)
        self.assertEqual(app_setting("demo", "theme", "auto"), "dark")
        self.assertEqual(app_setting("demo", "start", "23:00"), "22:30")
        self.assertEqual(AppSetting.objects.get(key="idle").updated_by, self.staff)

        self.post(enabled=None, idle="20", theme="dark", start="22:30")
        self.assertEqual(app_setting("demo", "idle", 5), 20)

    def test_invalid_value_shows_error_and_saves_nothing(self):
        self.client.force_login(self.staff)
        response = self.post(idle="90", theme="dark")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Some values need fixing", status_code=400)
        self.assertContains(response, 'value="90"', status_code=400)
        self.assertContains(response, " data-dirty>", status_code=400)  # the unsaved values can be saved again
        self.assertFalse(AppSetting.objects.exists())

    def test_save_waits_for_a_change(self):
        self.client.force_login(self.staff)
        page = self.client.get(self.url)
        self.assertContains(page, 'class="hst-btn" data-save>Save')
        self.assertNotContains(page, " data-dirty>")
        self.assertContains(page, ".hst-btn:disabled")

    def test_reset_deletes_saved_value(self):
        self.client.force_login(self.staff)
        self.post(idle="15")
        self.client.post(self.url, {"reset": "idle"})
        self.assertFalse(AppSetting.objects.filter(key="idle").exists())
        self.assertEqual(app_setting("demo", "idle", 5), 5)

    def test_environment_is_shown_as_default(self):
        self.client.force_login(self.staff)
        with self.settings(BDH_DEMO_TITLE="From env"):
            response = self.client.get(self.url)
        self.assertContains(response, 'value="From env"')

    def test_multi_setting_checkboxes(self):
        spec = PluginSpec(id="multi", app="multi", settings=(
            Setting("rooms", "Rooms", type=MULTI, default=None, choices_from="hub_settings.tests._rooms"),
            Setting("idle", "Idle after", type=INT, default=5),
        ))
        url = "/settings/app/multi/"
        self.client.force_login(self.staff)
        with self.settings(HUB_PLUGINS=PLUGINS + (spec,)):
            page = self.client.get(url)
            self.assertContains(page, 'value="u1"')
            self.assertContains(page, "Kitchen")
            self.assertContains(page, 'name="rooms__unset"')

            # Saving another setting doesn't turn "never picked" into "none".
            self.client.post(url, {"idle": "9", "rooms__unset": "1"})
            self.assertFalse(AppSetting.objects.filter(app_id="multi", key="rooms").exists())

            self.client.post(url, {"idle": "9", "rooms": ["u2", "u1"], "rooms__unset": "1"})
            self.assertEqual(app_setting("multi", "rooms", None), ["u2", "u1"])

            # Once saved, ticking nothing saves an empty list.
            self.client.post(url, {"idle": "9"})
            self.assertEqual(AppSetting.objects.get(app_id="multi", key="rooms").value, [])

            # A picked value no longer offered stays listed and ticked.
            AppSetting.objects.filter(app_id="multi", key="rooms").update(value=["gone"])
            page = self.client.get(url)
            self.assertContains(page, 'value="gone" checked')

    def test_app_with_only_settings_pages(self):
        spec = PluginSpec(id="pages", app="pages", settings_pages=(
            SettingsPage("Feeds", "hub_settings_home", subtitle="iCal links", icon="fas fa-rss"),
            SettingsPage("Broken", "no_such_url"),
        ))
        self.client.force_login(self.staff)
        with self.settings(HUB_PLUGINS=PLUGINS + (spec,)):
            page = self.client.get("/settings/app/pages/")
            self.assertContains(page, 'href="/settings/app/pages/"')
            self.assertContains(page, f'href="{reverse("hub_settings_home")}"')
            self.assertContains(page, "iCal links")
            self.assertNotContains(page, "Broken")
            self.assertNotContains(page, " data-save>")

    def test_layout_nav_available_to_app_pages(self):
        from django.template.loader import render_to_string
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        spec = PluginSpec(id="pages", app="pages",
                          settings_pages=(SettingsPage("Feeds", "hub_settings_home"),))
        request = RequestFactory().get("/pages/settings/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = self.staff
        with self.settings(HUB_PLUGINS=PLUGINS + (spec,)):
            html = render_to_string("hub_settings/_layout.html", {"active": "pages"}, request=request)
        self.assertIn('href="/settings/app/pages/" class="on"', html)
        self.assertIn(reverse("hub_settings_apps"), html)

    def test_menu_link_for_staff(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("hub_settings_apps")), 'href="/settings/"')


class HomeLayoutPageTests(TestCase):
    url = "/settings/home/"

    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")

    def saved(self):
        return AppSetting.objects.get(app_id="hub", key="home_layout").value

    def test_staff_only(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lists_tiles_and_nav_entry(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-id="hub:weather"')
        self.assertContains(response, 'href="/settings/home/"')
        self.assertContains(response, "Home layout")
        self.assertNotContains(response, "/admin/auth/user/")
        self.assertNotContains(response, 'href="/admin/"')

    def test_save_keeps_known_tiles_and_valid_sizes(self):
        self.client.force_login(self.staff)
        layout = {"groups": [
            {"key": "g-fav", "title": "  Favourites ", "tiles": [
                {"id": "hub:weather", "size": "s"}, {"id": "nope:x", "size": "m"}, {"id": "hub:lodge", "size": "xl"}]},
            {"key": "more", "title": "More", "tiles": [{"id": "hub:weather", "size": "l"}]},
        ]}
        response = self.client.post(self.url, {"layout": json.dumps(layout)})
        self.assertRedirects(response, self.url + "?saved=1")
        self.assertEqual(self.saved(), {"groups": [
            {"key": "g-fav", "title": "Favourites", "tiles": [{"id": "hub:weather", "size": "s"}]},
            {"key": "more", "title": "More", "tiles": []},
        ]})
        self.assertEqual(AppSetting.objects.get(key="home_layout").updated_by, self.staff)
        # The renamed group and an empty one both show on the settings page.
        page = self.client.get(self.url)
        self.assertContains(page, 'value="Favourites"')
        self.assertContains(page, 'data-key="more"')

    def test_bad_layout_is_rejected(self):
        self.client.force_login(self.staff)

        def group(key="more", title="More", tiles=()):
            return {"key": key, "title": title, "tiles": list(tiles)}

        for layout in ("{nope", "[]", {"mountain": [{"id": "hub:weather", "size": "s"}]}, {"groups": []},
                       {"groups": [group(key="Bad Key")]}, {"groups": [group(), group()]},
                       {"groups": [group(title="  ")]}, {"groups": [group(title="x" * 41)]},
                       {"groups": [group(tiles=["x"])]}, {"groups": [group(key=f"g{i}") for i in range(13)]}):
            raw = layout if isinstance(layout, str) else json.dumps(layout)
            response = self.client.post(self.url, {"layout": raw})
            self.assertEqual(response.status_code, 400, raw)
            self.assertContains(response, " data-dirty>", status_code=400)
        self.assertFalse(AppSetting.objects.exists())
        page = self.client.get(self.url)
        self.assertContains(page, 'class="hst-btn" data-save>Save')
        self.assertContains(page, "form.bdhState")
        self.assertNotContains(page, " data-dirty>")

    def test_reset_deletes_layout(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, {"layout": json.dumps(
            {"groups": [{"key": "more", "title": "More", "tiles": [{"id": "hub:weather", "size": "s"}]}]})})
        self.assertContains(self.client.get(self.url), 'name="reset"')
        self.assertRedirects(self.client.post(self.url, {"reset": "1"}), self.url + "?saved=1")
        self.assertFalse(AppSetting.objects.exists())


@override_settings(HUB_PLUGINS=QUICK_PLUGINS)
class QuickActionsPageTests(TestCase):
    url = "/settings/quick/"

    def setUp(self):
        cache.clear()
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")

    def saved(self):
        return AppSetting.objects.get(app_id="hub", key="quick").value

    def post(self, **value):
        body = {"grouped": True, "pinned": [], "order": [], "modes": {}}
        body.update(value)
        return self.client.post(self.url, {"quick": json.dumps(body)})

    def test_staff_only(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lists_apps_buttons_and_modes(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, 'href="/settings/quick/"')
        self.assertContains(response, 'data-id="announce"')
        self.assertContains(response, 'data-key="lights/lock_up"')
        # Each app gets a checkbox per mode.
        self.assertContains(response, 'data-mode="owner"', count=2)
        self.assertNotContains(response, "No installed app offers quick actions")

    def test_save_keeps_known_values_and_only_narrowing_modes(self):
        self.client.force_login(self.staff)
        response = self.post(grouped=False, pinned=["lights/movie", "lights/movie", "nope/x"],
                             order=["lights", "ghost"],
                             modes={"lights": ["guest", "dashboard", "owner"], "announce": ["owner", "bogus"],
                                    "ghost": ["owner"]})
        self.assertRedirects(response, self.url + "?saved=1")
        self.assertEqual(self.saved(), {"grouped": False, "pinned": ["lights/movie"], "order": ["lights"],
                                        "modes": {"announce": ["owner"]}})
        page = self.client.get(self.url)
        self.assertContains(page, 'data-key="lights/movie" aria-label="Pin Movie" checked')
        self.assertContains(page, 'name="reset"')

    def test_bad_value_is_rejected(self):
        self.client.force_login(self.staff)
        for raw in ("{nope", "[]", json.dumps({"pinned": [], "order": [], "modes": {}}),
                    json.dumps({"grouped": "yes", "pinned": [], "order": [], "modes": {}}),
                    json.dumps({"grouped": True, "pinned": {}, "order": [], "modes": {}}),
                    json.dumps({"grouped": True, "pinned": [], "order": [], "modes": []})):
            response = self.client.post(self.url, {"quick": raw})
            self.assertEqual(response.status_code, 400, raw)
            self.assertContains(response, " data-dirty>", status_code=400)
        self.assertFalse(AppSetting.objects.exists())

    def test_reset_deletes_prefs(self):
        self.client.force_login(self.staff)
        self.post(grouped=False)
        self.assertRedirects(self.client.post(self.url, {"reset": "1"}), self.url + "?saved=1")
        self.assertFalse(AppSetting.objects.exists())

    @override_settings(HUB_PLUGINS=())
    def test_empty_state(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.url), "No installed app offers quick actions")


class SettingsValidationTests(TestCase):
    def test_duplicate_setting_keys_rejected(self):
        spec = PluginSpec(id="dup", app="dup", settings=(Setting("a", "A"), Setting("a", "Again")))
        with self.assertRaisesMessage(PluginError, "duplicate setting"):
            validate([spec])

    def test_non_setting_rejected(self):
        spec = PluginSpec(id="bad", app="bad", settings=("a",))
        with self.assertRaisesMessage(PluginError, "is not a Setting"):
            validate([spec])


class AppStateTests(TestCase):
    def test_app_state_is_stored_in_database(self):
        state = app_state("display")
        state.set("lifts_opened", "2026-11-21")
        state.set("lifts_opened", "2026-11-22")
        self.assertEqual(AppState.objects.get(app_id="display").value, "2026-11-22")
        self.assertEqual(state.get("lifts_opened"), "2026-11-22")
        self.assertEqual(state.keys(), ["lifts_opened"])
        self.assertIsNone(app_state("other").get("lifts_opened"))
        state.delete("lifts_opened")
        self.assertNotIn("lifts_opened", state)
        self.assertFalse(AppState.objects.exists())


SUN_PEAKS = {"name": "Sun Peaks", "admin1": "British Columbia", "country": "Canada", "country_code": "CA",
             "latitude": 50.88, "longitude": -119.91, "timezone": "America/Vancouver"}
WATERLOO = {"name": "Waterloo", "admin1": "Ontario", "country": "Canada", "country_code": "CA",
            "latitude": 43.46, "longitude": -80.52, "timezone": "America/Toronto"}
WATERLOO_BE = {"name": "Waterloo", "admin1": "Wallonia", "country": "Belgium", "country_code": "BE",
               "latitude": 50.71, "longitude": 4.4, "timezone": "Europe/Brussels"}


class LocationPageTests(TestCase):
    url = "/settings/location/"
    search = "/settings/location/search/"

    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.guest = User.objects.create_user("guest", password="pw")

    def post(self, **overrides):
        data = {"name": "Sun Peaks", "region": "British Columbia", "country": "Canada", "country_code": "ca",
                "latitude": "50.8833", "longitude": "-119.9", "geo_timezone": "America/Vancouver",
                "tz_auto": "on", "timezone": ""}
        data.update(overrides)
        return self.client.post(self.url, {k: v for k, v in data.items() if v is not None})

    def geocode(self, *rows):
        reply = mock.Mock()
        reply.json.return_value = {"results": list(rows)}
        return mock.patch("hub_settings.views.requests.get", return_value=reply)

    def test_staff_only(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(self.search, {"q": "sun"}).status_code, 302)

    def test_listed_first_in_settings(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, "Search for a city")
        self.assertEqual(response.context["lodge_sections"][0]["id"], "location")

    @override_settings(BDH_HUB_UNITS="metric")
    def test_units(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.url), '<input type="radio" name="units" value="metric" checked>')
        # Units save even when the city isn't valid, and only a real change resets the cache.
        with mock.patch("hub.status.forget_units") as forget, mock.patch.object(store, "TTL", 0):
            self.assertEqual(self.post(name="", units="imperial").status_code, 400)
            self.post(name="", units="imperial")
            self.post(name="", units="kelvin")
        self.assertEqual(forget.call_count, 1)
        self.assertEqual(AppSetting.objects.get(app_id="hub", key="units").value, "imperial")
        with mock.patch.object(store, "TTL", 0):
            page = self.client.get(self.url)
        self.assertContains(page, '<input type="radio" name="units" value="imperial" checked>')

    def test_save_with_automatic_time_zone(self):
        from bdh_sdk.location import location, tzinfo
        self.client.force_login(self.staff)
        response = self.post(timezone="Europe/Paris")
        self.assertRedirects(response, self.url + "?saved=1", fetch_redirect_response=False)
        saved = AppSetting.objects.get(app_id="hub", key="location").value
        self.assertEqual(saved["timezone"], "America/Vancouver")
        self.assertEqual(saved["country_code"], "CA")
        self.assertTrue(saved["tz_auto"])
        self.assertEqual(location().label, "Sun Peaks, British Columbia, Canada")
        self.assertEqual(str(tzinfo()), "America/Vancouver")
        self.assertContains(self.client.get(self.url + "?saved=1"), "50.88, -119.90")

    def test_save_with_chosen_time_zone(self):
        self.client.force_login(self.staff)
        self.post(tz_auto=None, timezone="America/Edmonton")
        saved = AppSetting.objects.get(app_id="hub", key="location").value
        self.assertEqual((saved["timezone"], saved["geo_timezone"], saved["tz_auto"]),
                         ("America/Edmonton", "America/Vancouver", False))

    def test_rejects_bad_values(self):
        self.client.force_login(self.staff)
        for overrides in ({"latitude": "91"}, {"longitude": "x"}, {"name": ""},
                          {"tz_auto": None, "timezone": "Mars/Base"},
                          {"geo_timezone": ""}):
            with self.subTest(**overrides):
                self.assertEqual(self.post(**overrides).status_code, 400)
        self.assertFalse(AppSetting.objects.filter(app_id="hub", key="location").exists())

    def test_search_returns_places(self):
        self.client.force_login(self.staff)
        with self.geocode(SUN_PEAKS) as get:
            data = self.client.get(self.search, {"q": "sun peaks"}).json()
        self.assertEqual(get.call_args.kwargs["params"]["name"], "sun peaks")
        self.assertEqual(data["results"][0]["label"], "Sun Peaks, British Columbia, Canada")
        self.assertEqual(data["results"][0]["timezone"], "America/Vancouver")

    def test_search_narrows_by_text_after_a_comma(self):
        self.client.force_login(self.staff)
        with self.geocode(WATERLOO, WATERLOO_BE) as get:
            data = self.client.get(self.search, {"q": "Waterloo, belgium"}).json()
        self.assertEqual(get.call_args.kwargs["params"]["name"], "Waterloo")
        self.assertEqual([p["country"] for p in data["results"]], ["Belgium"])

    def test_search_needs_two_letters(self):
        self.client.force_login(self.staff)
        with self.geocode(SUN_PEAKS) as get:
            self.assertEqual(self.client.get(self.search, {"q": "s"}).json(), {"results": []})
        get.assert_not_called()

    def test_search_failure_is_502(self):
        import requests
        self.client.force_login(self.staff)
        with mock.patch("hub_settings.views.requests.get", side_effect=requests.ConnectionError):
            self.assertEqual(self.client.get(self.search, {"q": "sun"}).status_code, 502)

