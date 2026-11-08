import importlib

from asgiref.sync import async_to_sync
from channels.testing import HttpCommunicator, WebsocketCommunicator
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from hub.loader import websocket_urlpatterns
from hub.plugins import PluginSpec
from hub.tests.ws_fixture import EchoConsumer

ECHO = PluginSpec(id="ws_echo", app="ws_echo",
                  websocket_routes="hub.tests.ws_fixture.websocket_urlpatterns")


class WebsocketRoutesTests(SimpleTestCase):
    def test_collects_routes_from_plugins(self):
        patterns = websocket_urlpatterns([ECHO])
        consumers = [getattr(p.callback, "consumer_class", None) for p in patterns]
        self.assertIn(EchoConsumer, consumers)
        self.assertIn("ws/test_echo/", [str(p.pattern) for p in patterns])

    def test_plugins_without_routes_contribute_nothing(self):
        self.assertEqual(websocket_urlpatterns([PluginSpec(id="a", app="a")]), [])


class AsgiApplicationTests(SimpleTestCase):
    def setUp(self):
        import BlackDiamondHub.asgi as asgi

        with override_settings(HUB_PLUGINS=(*settings.HUB_PLUGINS, ECHO)):
            self.application = importlib.reload(asgi).application
        self.addCleanup(importlib.reload, asgi)

    def test_websocket_path_reaches_plugin_consumer(self):
        async def run():
            comm = WebsocketCommunicator(
                self.application, "/ws/test_echo/",
                headers=[(b"origin", b"http://testserver"), (b"host", b"testserver")],
            )
            connected, _ = await comm.connect()
            await comm.disconnect()
            return connected

        self.assertTrue(async_to_sync(run)())

    def test_unknown_websocket_path_is_rejected(self):
        async def run():
            comm = WebsocketCommunicator(
                self.application, "/ws/nope/",
                headers=[(b"origin", b"http://testserver"), (b"host", b"testserver")],
            )
            try:
                connected, _ = await comm.connect()
            except ValueError:
                connected = False
            return connected

        self.assertFalse(async_to_sync(run)())

    def test_http_still_served(self):
        async def run():
            comm = HttpCommunicator(
                self.application, "GET", "/accounts/login/",
                headers=[(b"host", b"testserver")],
            )
            return await comm.get_response()

        response = async_to_sync(run)()
        self.assertEqual(response["status"], 200)
