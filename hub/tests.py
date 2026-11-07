from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from hub.loader import PluginError, load_plugins, validate
from hub.modes import tiles_for_mode
from hub.plugins import DASHBOARD, GUEST, OWNER, OWNER_ONLY, PluginSpec, Tile


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