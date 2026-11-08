import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings

from hub.loader import PluginError, load_plugins, validate
from hub.modes import tiles_for_mode
from hub.plugins import (
    ALL_MODES, DASHBOARD, GUEST, ON, OWNER, OWNER_ONLY, WARN, Card, PluginSpec, Reading, Shortcut,
    Status, Stay, Tile,
)
from hub.status import current_stay, home_data


def _tile(**kw):
    defaults = dict(title="T", url_name="wifi_qr", icon="wifi/hub/icon.svg", section="more")
    defaults.update(kw)
    return Tile(**defaults)


class LoaderValidationTests(SimpleTestCase):
    def test_loader_rejects_hook_that_is_not_a_dotted_path(self):
        with self.assertRaisesMessage(PluginError, "websocket_routes must be a dotted"):
            validate([PluginSpec(id="a", app="a", websocket_routes="routing")])
        with self.assertRaisesMessage(PluginError, "status must be a dotted"):
            validate([PluginSpec(id="a", app="a", status=print)])

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesMessage(PluginError, "duplicate plugin id"):
            validate([PluginSpec(id="a", app="a"), PluginSpec(id="a", app="b")])

    def test_rejects_duplicate_url_prefixes(self):
        with self.assertRaisesMessage(PluginError, "duplicate URL prefix"):
            validate([
                PluginSpec(id="a", app="a", urls="a.urls", url_prefix="x/"),
                PluginSpec(id="b", app="b", urls="b.urls", url_prefix="x/"),
            ])

    def test_rejects_unknown_section(self):
        with self.assertRaisesMessage(PluginError, "unknown section"):
            validate([PluginSpec(id="a", app="a", tiles=(_tile(section="garage"),))])

    def test_rejects_other_api_version(self):
        with self.assertRaisesMessage(PluginError, "hub API"):
            validate([PluginSpec(id="a", app="a", api_version=99)])

    def test_loads_entry_point_plugins(self):
        external = PluginSpec(id="external", app="external", urls="external.urls")
        ep = MagicMock()
        ep.load.return_value = external
        with patch("hub.loader.entry_points", return_value=[ep]) as eps:
            specs = load_plugins(["radiant.plugin.spec"])
        eps.assert_called_once_with(group="blackdiamondhub.plugins")
        self.assertEqual([s.id for s in specs], ["radiant", "external"])


class TileModeTests(SimpleTestCase):
    plugins = (
        PluginSpec(id="wifi", app="wifi", tiles=(_tile(title="WiFi"),)),
        PluginSpec(id="vacation_mode", app="vacation_mode", tiles=(
            _tile(title="Vacation", url_name="vacation_mode", modes=OWNER_ONLY),
        )),
        PluginSpec(id="ghost", app="ghost", tiles=(_tile(title="Ghost", url_name="no_such_url"),)),
    )

    def titles(self, mode):
        with override_settings(HUB_PLUGINS=self.plugins):
            return [t["title"] for _, _, tiles in tiles_for_mode(mode) for t in tiles]

    def test_owner_only_tiles_are_hidden_from_other_modes(self):
        self.assertEqual(self.titles(GUEST), ["WiFi"])
        self.assertEqual(self.titles(DASHBOARD), ["WiFi"])
        self.assertEqual(self.titles(OWNER), ["Vacation", "WiFi"])

    def test_tile_with_unknown_url_is_skipped(self):
        self.assertNotIn("Ghost", self.titles(OWNER))


class HomepageRegistryTests(TestCase):
    def setUp(self):
        cache.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        mock_get = patcher.start()
        self.addCleanup(patcher.stop)
        mock_get.return_value = MagicMock(status_code=200, content=b"")

    def test_homepage_renders_tiles_from_installed_plugins(self):
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], DASHBOARD)
        for href, icon in [
            ("/snow_report/", "snow_report/hub/icon.svg"),
            ("/radiant/", "radiant/hub/icon.svg"),
            ("/lift_status/", "lift_status/hub/icon.svg"),
        ]:
            self.assertContains(response, f'href="{href}"')
            self.assertContains(response, icon)

    def test_signed_in_user_gets_owner_mode(self):
        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertContains(response, "mode-owner")


class HealthCheckTests(TestCase):
    def test_healthz_ok_for_any_host(self):
        # The container probe uses 127.0.0.1, which is not in ALLOWED_HOSTS.
        response = self.client.get("/healthz", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_healthz_reports_database_failure(self):
        with patch("hub.health.connection.cursor", side_effect=Exception("db down")):
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")


class WebSocketOriginTests(SimpleTestCase):
    async def test_rejects_websocket_from_foreign_origin(self):
        from channels.testing import WebsocketCommunicator

        from BlackDiamondHub.asgi import application

        communicator = WebsocketCommunicator(
            application, "/ws/sonos_updates/", headers=[(b"origin", b"http://evil.example")]
        )
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

# ── Status lines and shortcuts ──────────────────────────────────────────

HOOK_STATE = {}


def ok_status():
    return Status("3 lights on", ON)


def failing_status():
    if HOOK_STATE.get("fail"):
        raise RuntimeError("boom")
    return Status("fine")


def slow_status():
    HOOK_STATE["release"].wait(5)
    return Status("late")


def demo_shortcuts():
    return [
        Shortcut(id="movie", title="Movie", icon="fa-solid fa-film", modes=ALL_MODES),
        Shortcut(id="lock_up", title="Lock up", icon="fa-solid fa-lock"),
    ]


def demo_run(shortcut_id):
    HOOK_STATE.setdefault("ran", []).append(shortcut_id)
    if HOOK_STATE.get("run_fails"):
        raise RuntimeError("HA down")
    return "Enjoy the show"


def _spec(id, **kw):
    return PluginSpec(id=id, app=id, tiles=(_tile(title=id),), **kw)


STATUS_PLUGINS = (
    _spec("lights", status="hub.tests.test_hub.ok_status",
          shortcuts="hub.tests.test_hub.demo_shortcuts", run_shortcut="hub.tests.test_hub.demo_run"),
    _spec("flaky", status="hub.tests.test_hub.failing_status"),
    PluginSpec(id="hidden", app="hidden", status="hub.tests.test_hub.ok_status",
               tiles=(_tile(title="Hidden", modes=OWNER_ONLY),)),
)


@override_settings(HUB_PLUGINS=STATUS_PLUGINS)
class HomeStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()

    def test_status_and_shortcuts_follow_mode(self):
        data = self.client.get("/hub/api/status/").json()
        self.assertEqual(data["mode"], DASHBOARD)
        self.assertEqual(data["status"]["lights"]["text"], "3 lights on")
        self.assertEqual(data["status"]["lights"]["level"], ON)
        self.assertNotIn("hidden", data["status"])
        self.assertEqual([s["id"] for s in data["shortcuts"]], ["movie"])
        self.assertEqual(data["shortcuts"][0]["url"], "/hub/api/shortcut/lights/movie/")

        self.client.force_login(User.objects.create_user("owner"))
        data = self.client.get("/hub/api/status/").json()
        self.assertIn("hidden", data["status"])
        self.assertEqual({s["id"] for s in data["shortcuts"]}, {"movie", "lock_up"})

    def test_failed_hook_serves_last_good_value_as_stale(self):
        self.assertFalse(home_data(DASHBOARD)["status"]["flaky"]["stale"])
        cache.delete("hub:status:flaky")
        HOOK_STATE["fail"] = True
        flaky = home_data(DASHBOARD)["status"]["flaky"]
        self.assertEqual(flaky["text"], "fine")
        self.assertTrue(flaky["stale"])

    def test_failed_hook_without_history_is_left_out(self):
        HOOK_STATE["fail"] = True
        self.assertNotIn("flaky", home_data(DASHBOARD)["status"])

    def test_slow_hook_does_not_block_the_homepage(self):
        HOOK_STATE["release"] = threading.Event()
        plugins = (_spec("slow", status="hub.tests.test_hub.slow_status"),)
        try:
            with override_settings(HUB_PLUGINS=plugins):
                started = time.monotonic()
                data = home_data(DASHBOARD, timeout=0.2)
            self.assertLess(time.monotonic() - started, 2)
            self.assertNotIn("slow", data["status"])
        finally:
            HOOK_STATE["release"].set()


@override_settings(HUB_PLUGINS=STATUS_PLUGINS)
class ShortcutApiTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()

    def test_runs_shortcut_offered_in_mode(self):
        response = self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertEqual(response.json(), {"ok": True, "message": "Enjoy the show"})
        self.assertEqual(HOOK_STATE["ran"], ["movie"])

    def test_running_shortcut_refreshes_status_and_shortcuts(self):
        home_data(DASHBOARD)
        self.assertIsNotNone(cache.get("hub:shortcuts:lights"))
        self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertIsNone(cache.get("hub:status:lights"))
        self.assertIsNone(cache.get("hub:shortcuts:lights"))

    def test_owner_only_shortcut_needs_sign_in(self):
        response = self.client.post("/hub/api/shortcut/lights/lock_up/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("ran", HOOK_STATE)

        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.post("/hub/api/shortcut/lights/lock_up/")
        self.assertEqual(response.status_code, 200)

    def test_unknown_plugin_or_shortcut_is_404(self):
        self.assertEqual(self.client.post("/hub/api/shortcut/nope/movie/").status_code, 404)
        self.assertEqual(self.client.post("/hub/api/shortcut/lights/nope/").status_code, 404)

    def test_requires_post_and_csrf(self):
        self.assertEqual(self.client.get("/hub/api/shortcut/lights/movie/").status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/hub/api/shortcut/lights/movie/").status_code, 403)
        self.assertNotIn("ran", HOOK_STATE)

    def test_handler_failure_returns_502(self):
        HOOK_STATE["run_fails"] = True
        response = self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])

    def test_loader_requires_shortcut_handler(self):
        with self.assertRaisesMessage(PluginError, "run_shortcut"):
            validate([PluginSpec(id="a", app="a", shortcuts="a.homepage.shortcuts")])

def demo_stay():
    if HOOK_STATE.get("stay_fails"):
        raise RuntimeError("HA down")
    return HOOK_STATE.get("stay")


LODGE_TZ = timezone(timedelta(hours=-7))
STAY_PLUGINS = (
    *STATUS_PLUGINS,
    PluginSpec(id="stays", app="stays", stay="hub.tests.test_hub.demo_stay"),
)


@override_settings(HUB_PLUGINS=STAY_PLUGINS)
class StayModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        HOOK_STATE.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        patcher.start().return_value = MagicMock(status_code=200, content=b"")
        self.addCleanup(patcher.stop)
        now = datetime.now(LODGE_TZ)
        self.checkout = (now + timedelta(days=2)).replace(hour=11, minute=0, second=0, microsecond=0)
        HOOK_STATE["stay"] = Stay("The Smiths", now - timedelta(days=1), self.checkout)

    def test_reported_stay_puts_homepage_in_guest_mode_with_welcome(self):
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], GUEST)
        self.assertContains(response, "Welcome, The Smiths")
        c = self.checkout
        self.assertContains(response, f"Checkout {c:%A}, {c:%b} {c.day} at 11 AM")
        self.assertEqual(self.client.get("/hub/api/status/").json()["mode"], GUEST)

    def test_no_stay_is_dashboard_without_welcome(self):
        HOOK_STATE["stay"] = None
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], DASHBOARD)
        self.assertNotContains(response, "hub-welcome\"")

    def test_owner_mode_wins_and_skips_welcome(self):
        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertNotContains(response, "Welcome, The Smiths")

    def test_failed_hook_keeps_last_stay_until_checkout(self):
        self.assertIsNotNone(current_stay())
        cache.delete("hub:stay:stays")
        HOOK_STATE["stay_fails"] = True
        self.assertEqual(current_stay()["guest"], "The Smiths")
        cache.delete("hub:stay:stays")
        self.assertIsNone(current_stay(now=self.checkout + timedelta(minutes=1)))

    def test_hook_returning_wrong_type_is_ignored(self):
        HOOK_STATE["stay"] = "The Smiths"
        self.assertIsNone(current_stay())

    @override_settings(HUB_OWNER_VISIT_USER="lodge")
    def test_owner_visit_signs_the_hub_in(self):
        User.objects.create_user("lodge")
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertEqual(response.context["user"].username, "lodge")
        self.assertEqual(self.client.get("/hub/api/status/").json()["mode"], OWNER)
        # Not remembered: the hub is back to the dashboard once the visit ends.
        cache.clear()
        HOOK_STATE["stay"] = None
        self.assertEqual(self.client.get("/").context["hub_mode"], DASHBOARD)

    @override_settings(HUB_OWNER_VISIT_USER="lodge")
    def test_guest_stay_or_missing_user_does_not_sign_in(self):
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        cache.clear()
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)

    def test_owner_visit_without_setting_is_guest_mode(self):
        User.objects.create_user("lodge")
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)


def demo_card():
    return HOOK_STATE.get("card")


CARD_PLUGINS = (
    *STAY_PLUGINS,
    PluginSpec(id="lodge", app="lodge", card="hub.tests.test_hub.demo_card"),
)


@override_settings(HUB_PLUGINS=CARD_PLUGINS)
class LodgeCardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        HOOK_STATE.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        patcher.start().return_value = MagicMock(status_code=200, content=b"")
        self.addCleanup(patcher.stop)
        HOOK_STATE["card"] = Card(
            "Vacation mode", "Next: The Smiths",
            readings=(Reading("Inside", 14.5, "C"),),
            alerts=("Fireplace off: didn't complete",),
            url_name="wifi_qr", level=WARN,
        )

    def test_card_with_alerts_and_link_for_dashboard_and_owner(self):
        card = self.client.get("/hub/api/status/").json()["card"]
        self.assertEqual(card["title"], "Vacation mode")
        self.assertEqual(card["readings"], [{"label": "Inside", "value": 14.5, "unit": "C"}])
        self.assertEqual(card["alerts"], ["Fireplace off: didn't complete"])
        self.assertEqual((card["url"], card["level"]), ("/wifi/", WARN))

        response = self.client.get("/")
        self.assertEqual(response.context["hub_card"]["title"], "Vacation mode")
        self.assertContains(response, 'id="hub-card-data"')
        self.assertNotContains(response, 'class="hub-welcome"')

    def test_guests_get_no_alerts_or_link(self):
        HOOK_STATE["stay"] = Stay("The Smiths")
        card = self.client.get("/hub/api/status/").json()["card"]
        self.assertEqual((card["alerts"], card["url"], card["level"]), ([], None, "info"))
        self.assertEqual(card["readings"][0]["label"], "Inside")

    def test_no_card_is_null(self):
        HOOK_STATE["card"] = None
        self.assertIsNone(self.client.get("/hub/api/status/").json()["card"])
