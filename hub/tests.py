import threading
import time
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings

from hub.loader import PluginError, load_plugins, validate
from hub.modes import tiles_for_mode
from hub.plugins import (
    ALL_MODES, DASHBOARD, GUEST, ON, OWNER, OWNER_ONLY, PluginSpec, Shortcut, Status, Tile,
)
from hub.status import home_data


def _tile(**kw):
    defaults = dict(title="T", url_name="wifi_qr", icon="wifi/hub/icon.svg", section="more")
    defaults.update(kw)
    return Tile(**defaults)


class LoaderValidationTests(SimpleTestCase):
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
            specs = load_plugins(["wifi.plugin.spec"])
        eps.assert_called_once_with(group="blackdiamondhub.plugins")
        self.assertEqual([s.id for s in specs], ["wifi", "external"])


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
            ("/wifi/", "wifi/hub/icon.svg"),
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
    _spec("lights", status="hub.tests.ok_status",
          shortcuts="hub.tests.demo_shortcuts", run_shortcut="hub.tests.demo_run"),
    _spec("flaky", status="hub.tests.failing_status"),
    PluginSpec(id="hidden", app="hidden", status="hub.tests.ok_status",
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
        plugins = (_spec("slow", status="hub.tests.slow_status"),)
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