import asyncio
import importlib
import time
from unittest import mock

from asgiref.sync import async_to_sync
from bdh_sdk.alerts import Alert, push
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, tag
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from hub import alerts
from tests.selenium_helpers import SeleniumTestCase, wait_for_paint

HEADERS = [(b"origin", b"http://testserver"), (b"host", b"testserver")]


def doorbell(**kw):
    return Alert(**{"app": "cameras", "key": "doorbell:front", "title": "Front door",
                    "embed_url": "/cameras/popup/front/", "ttl": 45, **kw})


class AlertSocketTests(SimpleTestCase):
    def setUp(self):
        import BlackDiamondHub.asgi as asgi

        self.application = importlib.reload(asgi).application
        self.addCleanup(setattr, alerts, "_loop", None)

    def test_push_from_another_thread_reaches_connected_screens(self):
        async def run():
            screens = [WebsocketCommunicator(self.application, "/ws/hub/alerts/", headers=HEADERS)
                       for _ in range(2)]
            for comm in screens:
                connected, _ = await comm.connect()
                self.assertTrue(connected)
            # Apps push from their own worker threads, not the server loop.
            await asyncio.to_thread(push, doorbell(body="Someone is at the door"))
            received = [await comm.receive_json_from(timeout=2) for comm in screens]
            for comm in screens:
                await comm.disconnect()
            return received

        for msg in async_to_sync(run)():
            self.assertEqual(msg, {
                "type": "alert", "app": "cameras", "key": "doorbell:front", "title": "Front door",
                "body": "Someone is at the door", "embed_url": "/cameras/popup/front/",
                "ttl": 45, "wake": True, "sound": None,
            })

    def test_push_with_no_screens_connected_is_dropped(self):
        alerts._loop = None
        with mock.patch("hub.alerts.asyncio.run_coroutine_threadsafe") as send:
            push(doorbell())
        send.assert_not_called()


class AlertTestHookTests(TestCase):
    def test_requires_staff(self):
        self.client.force_login(User.objects.create_user("guest"))
        with mock.patch("bdh_sdk.alerts.push") as sent:
            response = self.client.get("/hub/api/alerts/test/")
        self.assertEqual(response.status_code, 302)
        sent.assert_not_called()

    def test_staff_can_push_a_sample(self):
        self.client.force_login(User.objects.create_user("owner", is_staff=True))
        with mock.patch("bdh_sdk.alerts.push") as sent:
            response = self.client.get("/hub/api/alerts/test/?ttl=10")
        self.assertEqual(response.json(), {"ok": True})
        alert = sent.call_args.args[0]
        self.assertEqual((alert.key, alert.ttl, alert.embed_url),
                         ("hub:test", 10, "/hub/api/alerts/sample/"))
        self.assertEqual(self.client.get(alert.embed_url).status_code, 200)

    def test_rejects_an_off_site_embed(self):
        self.client.force_login(User.objects.create_user("owner", is_staff=True))
        response = self.client.get("/hub/api/alerts/test/?embed=//evil.example/")
        self.assertEqual(response.status_code, 400)


@tag("selenium")
class AlertKeepOpenTest(SeleniumTestCase):
    SHOWN = (By.CSS_SELECTOR, ".hub-alert.on")

    def show(self, ttl):
        self.browser.execute_script(
            "BDHAlerts.show({key: 'k', title: 'Door', embed_url: '/hub/api/alerts/sample/',"
            " ttl: arguments[0]})", ttl)

    def test_keep_open_stops_the_countdown_until_closed(self):
        browser = self.browser
        browser.get(f"{self.live_server_url}/accounts/login/")
        wait_for_paint(browser)
        self.show(1)
        keep = WebDriverWait(browser, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".hub-alert-keep")))
        keep.click()
        self.assertEqual(keep.get_attribute("aria-pressed"), "true")
        self.show(1)  # a repeat (another ring) must not restart the countdown
        time.sleep(2)
        self.assertTrue(browser.find_elements(*self.SHOWN))

        browser.find_element(By.CSS_SELECTOR, ".hub-alert-close").click()
        WebDriverWait(browser, 5).until(EC.invisibility_of_element_located(self.SHOWN))
        self.show(1)  # a fresh alert counts down again
        self.assertEqual(keep.get_attribute("aria-pressed"), "false")
        WebDriverWait(browser, 5).until(EC.invisibility_of_element_located(self.SHOWN))
