import json

from bdh_sdk.plugins import BOOL, CHOICE, INT, TIME
from bdh_sdk.settings import app_setting
from bdh_sdk.storage import app_state
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from hub.loader import PluginError, validate
from hub.plugins import PluginSpec, Setting

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
        self.assertFalse(AppSetting.objects.exists())

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

    def test_save_keeps_known_tiles_and_valid_sizes(self):
        self.client.force_login(self.staff)
        layout = {"mountain": [{"id": "hub:weather", "size": "s"}, {"id": "hub:weather", "size": "l"},
                               {"id": "nope:x", "size": "m"}],
                  "garage": [{"id": "hub:weather", "size": "m"}]}
        response = self.client.post(self.url, {"layout": json.dumps(layout)})
        self.assertRedirects(response, self.url + "?saved=1")
        self.assertEqual(self.saved(), {"mountain": [{"id": "hub:weather", "size": "s"}]})
        self.assertEqual(AppSetting.objects.get(key="home_layout").updated_by, self.staff)

    def test_bad_layout_is_rejected(self):
        self.client.force_login(self.staff)
        for raw in ("{nope", "[]", '{"mountain": ["x"]}'):
            response = self.client.post(self.url, {"layout": raw})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(AppSetting.objects.exists())

    def test_reset_deletes_layout(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, {"layout": json.dumps({"mountain": [{"id": "hub:weather", "size": "s"}]})})
        self.assertContains(self.client.get(self.url), 'name="reset"')
        self.assertRedirects(self.client.post(self.url, {"reset": "1"}), self.url + "?saved=1")
        self.assertFalse(AppSetting.objects.exists())


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
