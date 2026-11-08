from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.testing import HttpCommunicator, WebsocketCommunicator
from django.test import SimpleTestCase

from hub.loader import websocket_urlpatterns
from hub.plugins import PluginSpec
from sonos_control.consumers import SonosConsumer


async def _accept_only(self):
    await self.accept()


async def _noop_disconnect(self, close_code):
    pass


class WebsocketRoutesTests(SimpleTestCase):
    def test_collects_routes_from_installed_plugins(self):
        patterns = websocket_urlpatterns()
        consumers = [getattr(p.callback, "consumer_class", None) for p in patterns]
        self.assertIn(SonosConsumer, consumers)
        self.assertIn("ws/sonos_updates/", [str(p.pattern) for p in patterns])

    def test_plugins_without_routes_contribute_nothing(self):
        self.assertEqual(websocket_urlpatterns([PluginSpec(id="a", app="a")]), [])


@patch.object(SonosConsumer, "disconnect", _noop_disconnect)
@patch.object(SonosConsumer, "connect", _accept_only)
class AsgiApplicationTests(SimpleTestCase):
    def setUp(self):
        from BlackDiamondHub.asgi import application

        self.application = application

    def test_websocket_path_reaches_sonos_consumer(self):
        async def run():
            comm = WebsocketCommunicator(
                self.application, "/ws/sonos_updates/",
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
