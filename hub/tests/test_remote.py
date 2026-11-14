import asyncio
import importlib
import os
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import SimpleTestCase, TestCase, tag
from selenium.webdriver.support.ui import WebDriverWait

from hub import remote
from tests.selenium_helpers import SeleniumTestCase, wait_for_paint

HEADERS = [(b"origin", b"http://testserver"), (b"host", b"testserver")]
TOKEN = {"HUB_REMOTE_TOKEN": "t0ken"}


@mock.patch.dict(os.environ, TOKEN)
class RemoteApiTests(SimpleTestCase):
    def setUp(self):
        import BlackDiamondHub.asgi as asgi

        self.application = importlib.reload(asgi).application
        self.addCleanup(remote._screens.clear)

    async def screen(self, path="/cameras/"):
        comm = WebsocketCommunicator(self.application, "/ws/hub/remote/", headers=HEADERS)
        comm.scope["client"] = ["10.0.0.5", 50000]
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        await comm.send_json_to({"type": "hello", "path": path, "title": "Hub", "size": [1920, 1080], "ua": "Screen"})
        await asyncio.sleep(0.05)
        return comm

    def test_forwards_a_command_and_returns_the_reply(self):
        async def run():
            comm = await self.screen()
            listing = (await self.async_client.get("/hub/api/remote/", headers={"X-Hub-Token": "t0ken"})).json()
            request = asyncio.ensure_future(self.async_client.post(
                "/hub/api/remote/", {"cmd": "tap", "args": {"text": "Driveway"}},
                content_type="application/json", headers={"X-Hub-Token": "t0ken"}))
            command = await comm.receive_json_from(timeout=2)
            await comm.send_json_to({"type": "result", "id": command["id"], "ok": True, "value": {"at": [5, 6]}})
            response = await request
            await comm.disconnect()
            return listing, command, response

        listing, command, response = async_to_sync(run)()
        screen = listing["screens"][0]
        self.assertEqual((screen["path"], screen["size"], screen["ua"]), ("/cameras/", [1920, 1080], "Screen"))
        self.assertEqual((command["cmd"], command["args"]), ("tap", {"text": "Driveway"}))
        self.assertEqual(response.json(), {"ok": True, "value": {"at": [5, 6]}})

    def test_targets_by_ip_and_times_out(self):
        async def run():
            comm = await self.screen()
            missing = await self.async_client.post(
                "/hub/api/remote/", {"cmd": "state", "target": "10.9.9.9"},
                content_type="application/json", headers={"X-Hub-Token": "t0ken"})
            silent = await self.async_client.post(
                "/hub/api/remote/", {"cmd": "state", "target": "10.0.0.5", "timeout": 0.2},
                content_type="application/json", headers={"X-Hub-Token": "t0ken"})
            await comm.disconnect()
            return missing, silent

        missing, silent = async_to_sync(run)()
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(silent.status_code, 504)
        self.assertEqual(remote._pending, {})

    def test_rejects_a_wrong_token(self):
        response = self.client.get("/hub/api/remote/", headers={"X-Hub-Token": "nope"})
        self.assertEqual(response.status_code, 403)


class RemoteOffTests(TestCase):
    @mock.patch.dict(os.environ, {"HUB_REMOTE_TOKEN": ""})
    def test_off_without_a_token(self):
        import BlackDiamondHub.asgi as asgi

        application = importlib.reload(asgi).application

        async def connect():
            comm = WebsocketCommunicator(application, "/ws/hub/remote/", headers=HEADERS)
            connected, _ = await comm.connect()
            return connected

        self.assertFalse(async_to_sync(connect)())
        self.assertEqual(self.client.get("/hub/api/remote/").status_code, 404)
        self.assertNotIn("hub/remote.js", self.client.get("/").content.decode())

    @mock.patch.dict(os.environ, TOKEN)
    def test_pages_load_the_remote_when_on(self):
        self.assertIn("hub/remote.js", self.client.get("/").content.decode())


@tag("selenium")
class RemoteFullscreenTest(SeleniumTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, TOKEN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_remote_tap_gets_a_stand_in_fullscreen_with_the_page_styles(self):
        browser = self.browser
        browser.get(f"{self.live_server_url}/accounts/login/")
        wait_for_paint(browser)
        WebDriverWait(browser, 5).until(lambda b: b.execute_script("return !!window.BDHRemote"))
        browser.execute_script("""
            const style = document.createElement('style');
            style.textContent = '#card:fullscreen { color: rgb(1, 2, 3); }';
            document.head.appendChild(style);
            const card = document.createElement('button');
            card.id = 'card';
            card.textContent = 'Driveway';
            card.onclick = () => card.requestFullscreen();
            document.body.appendChild(card);
            window.changes = 0;
            document.addEventListener('fullscreenchange', () => window.changes++);
        """)
        tapped = browser.execute_async_script(
            "const done = arguments[0];"
            "BDHRemote.commands.tap({text: 'Driveway'})"
            ".then(r => done(r.target.id), e => done('tap failed: ' + (e.stack || e)));")
        self.assertEqual(tapped, "card")
        WebDriverWait(browser, 5).until(lambda b: b.execute_script("return window.changes === 1"))
        self.assertEqual(browser.execute_script(
            "return [document.fullscreenElement.id, getComputedStyle(document.fullscreenElement).color,"
            " BDHRemote.state().fullscreen_kind]"), ["card", "rgb(1, 2, 3)", "stand-in"])

        browser.execute_script("document.exitFullscreen()")
        self.assertEqual(browser.execute_script("return [document.fullscreenElement, window.changes]"), [None, 2])
