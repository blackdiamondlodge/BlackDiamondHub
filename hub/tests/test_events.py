"""Event sources: site config, the Home Assistant source and the webhook."""
import json
import os
from unittest.mock import MagicMock, patch

from bdh_sdk import events
from django.test import Client, SimpleTestCase, override_settings

from hub import events as hub_events
from hub.site import event_sources


class Recorder:
    def __init__(self, pattern):
        self.got = []
        self.sub = events.subscribe(pattern, self.got.append)

    def wait(self):
        events.flush(5)
        return self.got


class EventSourceConfigTests(SimpleTestCase):
    def test_valid_sources(self):
        sources = {"ha": {"type": "home_assistant"}, "hook": {"type": "webhook", "secret_env": "X"}}
        self.assertEqual(event_sources("s", sources), sources)

    def test_rejects_bad_sources(self):
        for sources, error in [
            ({"ha": {"type": "mqtt"}}, "type must be"),
            ({"ha/x": {"type": "home_assistant"}}, "bad source name"),
            ({"hook": {"type": "webhook"}}, "secret_env"),
            ({"ha": "home_assistant"}, "must be a table"),
        ]:
            with self.subTest(sources=sources), self.assertRaisesRegex(ValueError, error):
                event_sources("s", sources)


class ShouldStartTests(SimpleTestCase):
    def test_server_processes_only(self):
        with patch.dict(os.environ, {"RUN_MAIN": "true"}):
            self.assertTrue(hub_events.should_start(["/app/.venv/bin/daphne", "x"]))
            self.assertTrue(hub_events.should_start(["manage.py", "runserver"]))
            self.assertFalse(hub_events.should_start(["manage.py", "migrate"]))
        with patch.dict(os.environ, {"RUN_MAIN": ""}):
            self.assertFalse(hub_events.should_start(["manage.py", "runserver"]))
        with patch.dict(os.environ, {"HUB_EVENTS": "off"}):
            self.assertFalse(hub_events.should_start(["daphne"]))


class HomeAssistantSourceTests(SimpleTestCase):
    def setUp(self):
        events.reset()
        self.addCleanup(events.reset)

    def test_wanted_entities(self):
        want = hub_events.wanted_entities
        self.assertEqual(want("ha", []), set())
        self.assertEqual(want("ha", ["ha/state/binary_sensor.door", "other/state/x.y", "ha/state/light.a"]),
                         {"binary_sensor.door", "light.a"})
        self.assertIsNone(want("ha", ["ha/state/+"]))
        self.assertIsNone(want("ha", ["ha/#"]))
        self.assertIsNone(want("ha", ["#"]))
        self.assertEqual(want("ha", ["ha/other/+"]), set())

    def test_pattern_change_drops_the_connection(self):
        source = hub_events.HomeAssistantSource("ha", "http://ha.local:8123", "token")
        self.assertEqual(source.url, "ws://ha.local:8123/api/websocket")
        source._ws = ws = MagicMock()
        source._patterns_changed(["ha/state/binary_sensor.door"])
        ws.close.assert_called_once()
        self.assertEqual(source.entities, {"binary_sensor.door"})
        ws.reset_mock()
        source._patterns_changed(["ha/state/binary_sensor.door", "other/x"])
        ws.close.assert_not_called()

    def test_publishes_trigger_and_state_changed_events(self):
        rec = Recorder("ha/state/#")
        source = hub_events.HomeAssistantSource("ha", "https://ha.local", "token")
        source._handle({"type": "event", "event": {"variables": {"trigger": {
            "entity_id": "binary_sensor.door",
            "from_state": {"state": "off"},
            "to_state": {"state": "on", "attributes": {"friendly_name": "Front Door"}}}}}})
        source._handle({"type": "event", "event": {"event_type": "state_changed", "data": {
            "entity_id": "light.a", "old_state": None, "new_state": {"state": "on"}}}})
        source._handle({"type": "result", "success": True})
        got = rec.wait()
        self.assertEqual([e.topic for e in got], ["ha/state/binary_sensor.door", "ha/state/light.a"])
        self.assertEqual(got[0].data, {"entity_id": "binary_sensor.door", "old": "off", "new": "on",
                                       "attributes": {"friendly_name": "Front Door"}})
        self.assertEqual(got[1].data["old"], None)

    def test_failed_subscription_reconnects(self):
        source = hub_events.HomeAssistantSource("ha", "http://ha", "token")
        with self.assertRaisesRegex(ConnectionError, "subscribe failed"):
            source._handle({"type": "result", "success": False, "error": {"code": "x"}})


HOOKS = {"hook": {"type": "webhook", "secret_env": "TEST_HOOK_SECRET"}, "ha": {"type": "home_assistant"}}


@override_settings(HUB_EVENT_SOURCES=HOOKS)
class WebhookTests(SimpleTestCase):
    def setUp(self):
        events.reset()
        self.addCleanup(events.reset)
        self.client = Client()

    def post(self, path, body=b"", secret="s3cret"):
        headers = {"HTTP_X_HUB_SECRET": secret} if secret else {}
        return self.client.post(f"/hub/api/events/hook/{path}", body,
                                content_type="application/json", **headers)

    @patch.dict(os.environ, {"TEST_HOOK_SECRET": "s3cret"})
    def test_publishes_json_body(self):
        rec = Recorder("hook/#")
        r = self.post("hook/garage/door", json.dumps({"open": True}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        r = self.post("hook/ping")
        self.assertEqual(r.status_code, 200)
        got = rec.wait()
        self.assertEqual([(e.topic, e.data) for e in got],
                         [("hook/garage/door", {"open": True}), ("hook/ping", None)])

    @patch.dict(os.environ, {"TEST_HOOK_SECRET": "s3cret"})
    def test_rejects_bad_requests(self):
        rec = Recorder("#")
        self.assertEqual(self.post("hook/x", secret="wrong").status_code, 403)
        self.assertEqual(self.post("hook/x", secret="").status_code, 403)
        self.assertEqual(self.post("hook/x", b"{nope").status_code, 400)
        self.assertEqual(self.post("hook/a/+").status_code, 400)
        self.assertEqual(self.post("ha/x").status_code, 404)
        self.assertEqual(self.post("nope/x").status_code, 404)
        self.assertEqual(self.client.get("/hub/api/events/hook/hook/x").status_code, 405)
        self.assertEqual(rec.wait(), [])

    @patch.dict(os.environ, {"TEST_HOOK_SECRET": ""})
    def test_disabled_without_secret(self):
        self.assertEqual(self.post("hook/x", secret="").status_code, 403)
