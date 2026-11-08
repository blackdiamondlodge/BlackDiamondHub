"""
Tests for the device_control app.
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, tag
from django.urls import reverse
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from .device_config import TABS, get_all_entity_ids
from .ha_client import get_entity_state, get_entity_states, call_service
from . import views

# The FILTERABLE_TABS set must stay in sync with the JS in the template.
FILTERABLE_TABS = {"lights", "shades"}


class DeviceConfigTests(TestCase):
    """Tests for device_config.py."""

    def test_tabs_not_empty(self):
        self.assertTrue(len(TABS) > 0)

    def test_each_tab_has_required_keys(self):
        for tab in TABS:
            self.assertIn("key", tab)
            self.assertIn("label", tab)
            self.assertIn("icon", tab)
            self.assertIn("devices", tab)

    def test_get_all_entity_ids_returns_set(self):
        ids = get_all_entity_ids()
        self.assertIsInstance(ids, set)
        self.assertTrue(len(ids) > 0)

    def test_all_entity_ids_have_dot(self):
        """Every entity_id should be in domain.object_id format."""
        for eid in get_all_entity_ids():
            self.assertIn(".", eid, f"Entity ID missing dot: {eid}")

    def test_no_duplicate_entity_ids_within_tab(self):
        """No tab should list the same entity_id twice."""
        for tab in TABS:
            seen = set()
            for _group, devices in tab["devices"].items():
                for dev in devices:
                    eid = dev["entity_id"]
                    self.assertNotIn(eid, seen, f"Duplicate {eid} in tab {tab['key']}")
                    seen.add(eid)


class HaClientTests(TestCase):
    """Tests for ha_client.py (mocked HTTP)."""

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_state_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "entity_id": "switch.test",
            "state": "on",
            "attributes": {"friendly_name": "Test"},
        }
        mock_get.return_value = mock_resp

        result = get_entity_state("switch.test")
        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "on")

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_state_failure(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = get_entity_state("switch.nonexistent")
        self.assertIsNone(result)

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_states_filters(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"entity_id": "switch.a", "state": "on", "attributes": {}},
            {"entity_id": "switch.b", "state": "off", "attributes": {}},
            {"entity_id": "switch.c", "state": "on", "attributes": {}},
        ]
        mock_get.return_value = mock_resp

        result = get_entity_states(["switch.a", "switch.c"])
        self.assertEqual(len(result), 2)
        self.assertIn("switch.a", result)
        self.assertIn("switch.c", result)
        self.assertNotIn("switch.b", result)

    @patch("device_control.ha_client.requests.post")
    def test_call_service_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, error = call_service("switch", "turn_on", "switch.test")
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch("device_control.ha_client.requests.post")
    def test_call_service_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        success, error = call_service("switch", "turn_on", "switch.test")
        self.assertFalse(success)
        self.assertIn("500", error)


class ViewTests(TestCase):
    """Tests for device_control views."""

    def test_main_page_renders(self):
        resp = self.client.get(reverse("device_control"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Device Control")
        self.assertContains(resp, "dc-tab")

    def test_filter_bar_visible_on_initial_load(self):
        """The filter bar must not be hidden when the first tab is filterable."""
        first_tab_key = TABS[0]["key"]
        resp = self.client.get(reverse("device_control"))
        content = resp.content.decode()

        if first_tab_key in FILTERABLE_TABS:
            # Filter bar should NOT have the 'hidden' class
            self.assertNotIn(
                'dc-filter-bar hidden',
                content,
                "Filter bar is hidden on initial load but the first tab "
                f"('{first_tab_key}') is filterable — it should be visible.",
            )
        else:
            # Filter bar SHOULD have the 'hidden' class
            self.assertIn('dc-filter-bar hidden', content)

    def test_main_page_has_all_tabs(self):
        resp = self.client.get(reverse("device_control"))
        for tab in TABS:
            self.assertContains(resp, tab["label"])

    @patch("device_control.views.get_entity_states")
    def test_states_endpoint(self, mock_states):
        mock_states.return_value = {
            "switch.living_room_tv_socket_1": {
                "state": "on",
                "attributes": {"friendly_name": "Living Room TV Socket 1"},
            }
        }
        resp = self.client.get(reverse("device_control_states"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("switch.living_room_tv_socket_1", data)
        self.assertEqual(data["switch.living_room_tv_socket_1"]["state"], "on")

    def test_action_requires_post(self):
        resp = self.client.get(reverse("device_control_action"))
        self.assertEqual(resp.status_code, 405)

    @patch("device_control.views.call_service")
    def test_action_toggle_switch(self, mock_call):
        mock_call.return_value = (True, None)
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "on", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        mock_call.assert_called_once_with("switch", "turn_on", "switch.living_room_tv_socket_1", extra_data=None)

    def test_action_rejects_unknown_entity(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.evil_entity", "action": "on", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_action_rejects_bad_json(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_unknown_type(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "on", "type": "thermostat"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("device_control.views.call_service")
    def test_action_cover_open(self, mock_call):
        mock_call.return_value = (True, None)
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "cover.kitchen_left_window", "action": "open", "type": "cover"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        mock_call.assert_called_once_with("cover", "open_cover", "cover.kitchen_left_window", extra_data=None)

    @patch("device_control.views.call_service")
    def test_action_ha_error_returns_502(self, mock_call):
        mock_call.return_value = (False, "HA timeout")
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "off", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)
        data = resp.json()
        self.assertFalse(data["ok"])


REGISTRY = {
    "entities": {
        "switch.lr_power": {"entity_id": "switch.lr_power", "device_id": "dev1",
                            "platform": "napoleon", "translation_key": "fireplace_power"},
        "light.lr_ember": {"entity_id": "light.lr_ember", "device_id": "dev1",
                           "platform": "napoleon", "translation_key": "ember_bed"},
    },
    "devices": {"dev1": {"id": "dev1", "name": "Living Room", "name_by_user": None}},
    "config": {"unit_system": {"temperature": "°C"}},
}


class FireplaceViewTests(TestCase):
    """Tests for the HA-backed fireplace endpoints (mocked HA client)."""

    def setUp(self):
        views._fireplace_cache.clear()

    def _post(self, body):
        return self.client.post(
            reverse("device_control_fireplace_action"),
            data=body if isinstance(body, str) else json.dumps(body),
            content_type="application/json",
        )

    # ----- registry loading -----

    @patch("device_control.views.ws_commands")
    def test_registry_filters_to_napoleon(self, mock_ws):
        mock_ws.return_value = [
            [
                {"entity_id": "switch.lr_power", "device_id": "dev1", "platform": "napoleon",
                 "translation_key": "fireplace_power", "disabled_by": None, "extra": 1},
                {"entity_id": "switch.other", "device_id": "dev2", "platform": "hue",
                 "translation_key": None, "disabled_by": None},
                {"entity_id": "switch.lr_off", "device_id": "dev1", "platform": "napoleon",
                 "translation_key": "eco_mode", "disabled_by": "user"},
            ],
            [{"id": "dev1", "name": "Living Room", "name_by_user": "LR"}, {"id": "dev2", "name": "Hue"}],
            {"unit_system": {"temperature": "°F"}},
        ]
        reg = views._napoleon_registry()
        self.assertEqual(list(reg["entities"]), ["switch.lr_power"])
        self.assertNotIn("extra", reg["entities"]["switch.lr_power"])
        self.assertEqual(list(reg["devices"]), ["dev1"])
        self.assertEqual(reg["config"]["unit_system"]["temperature"], "°F")
        views._napoleon_registry()
        mock_ws.assert_called_once()  # cached

    # ----- states endpoint -----

    @patch("device_control.views.get_all_states")
    @patch("device_control.views._napoleon_registry", return_value=REGISTRY)
    def test_states_returns_napoleon_states_only(self, _reg, mock_states):
        mock_states.return_value = [
            {"entity_id": "switch.lr_power", "state": "on"},
            {"entity_id": "light.kitchen", "state": "on"},
        ]
        resp = self.client.get(reverse("device_control_fireplace_states"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(list(data["states"]), ["switch.lr_power"])
        self.assertIn("dev1", data["devices"])
        self.assertIn("light.lr_ember", data["entities"])

    @patch("device_control.views._napoleon_registry", side_effect=views.HAError("down"))
    def test_states_ha_error_returns_502(self, _reg):
        resp = self.client.get(reverse("device_control_fireplace_states"))
        self.assertEqual(resp.status_code, 502)
        self.assertIn("error", resp.json())

    # ----- action endpoint -----

    def test_action_requires_post(self):
        resp = self.client.get(reverse("device_control_fireplace_action"))
        self.assertEqual(resp.status_code, 405)

    def test_action_rejects_bad_json(self):
        self.assertEqual(self._post("not json").status_code, 400)

    def test_action_rejects_disallowed_service(self):
        resp = self._post({"domain": "lock", "service": "unlock", "data": {"entity_id": "lock.front"}})
        self.assertEqual(resp.status_code, 400)
        resp = self._post({"domain": "switch", "service": "toggle", "data": {"entity_id": "switch.lr_power"}})
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_domain_mismatch(self):
        resp = self._post({"domain": "switch", "service": "turn_on", "data": {"entity_id": "light.lr_ember"}})
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_unknown_fields(self):
        resp = self._post({"domain": "light", "service": "turn_on",
                           "data": {"entity_id": "light.lr_ember", "flash": "long"}})
        self.assertEqual(resp.status_code, 400)

    @patch("device_control.views.call_service")
    @patch("device_control.views._napoleon_registry", return_value=REGISTRY)
    def test_action_rejects_non_napoleon_entity(self, _reg, mock_call):
        resp = self._post({"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.garage"}})
        self.assertEqual(resp.status_code, 400)
        mock_call.assert_not_called()

    @patch("device_control.views.call_service", return_value=(True, None))
    @patch("device_control.views._napoleon_registry", return_value=REGISTRY)
    def test_action_success(self, _reg, mock_call):
        resp = self._post({"domain": "light", "service": "turn_on",
                           "data": {"entity_id": "light.lr_ember", "rgb_color": [255, 90, 30]}})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        mock_call.assert_called_once_with("light", "turn_on", "light.lr_ember", {"rgb_color": [255, 90, 30]})

    @patch("device_control.views.call_service", return_value=(False, "HA returned 500"))
    @patch("device_control.views._napoleon_registry", return_value=REGISTRY)
    def test_action_ha_error_returns_502(self, _reg, _call):
        resp = self._post({"domain": "switch", "service": "turn_off", "data": {"entity_id": "switch.lr_power"}})
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.json()["ok"])

    # ----- card proxy -----

    @patch("device_control.views.get_static", return_value=b"customElements.define('x', class {});")
    def test_card_proxied_and_cached(self, mock_static):
        for _ in range(2):
            resp = self.client.get(reverse("device_control_fireplace_card"))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "application/javascript")
        mock_static.assert_called_once_with(views.FIREPLACE_CARD_PATH)

    @patch("device_control.views.get_static", side_effect=views.HAError("404"))
    def test_card_unavailable_returns_502(self, _static):
        resp = self.client.get(reverse("device_control_fireplace_card"))
        self.assertEqual(resp.status_code, 502)


class FireplaceTabTests(TestCase):
    """The fireplace tab must render its dedicated panel structure."""

    def test_fireplace_panel_rendered(self):
        resp = self.client.get(reverse("device_control"))
        content = resp.content.decode()
        self.assertIn('id="panel-fireplace"', content)
        self.assertIn('id="fpSelect"', content)
        self.assertIn('id="fpCard"', content)
        self.assertIn('data-states-url', content)
        self.assertIn('data-action-url', content)
        self.assertIn('data-card-url', content)
        self.assertIn('fireplace.js', content)
        self.assertIn('fireplace.css', content)


class GemstoneViewTests(TestCase):
    """Tests for the Gemstone Lights endpoints (mocked gemstone_client)."""

    def _device(self, **over):
        base = {
            "id": "dev-123",
            "name": "Roofline",
            "online": True,
            "power": True,
            "pattern_id": "pat-1",
            "pattern_name": "Christmas",
            "pattern_colors": ["#ff0000", "#00ff00"],
        }
        base.update(over)
        return base

    def _pattern(self, **over):
        base = {
            "id": "pat-1",
            "name": "Christmas",
            "colors": ["#ff0000", "#00ff00"],
            "is_favorite": True,
        }
        base.update(over)
        return base

    # ----- states endpoint -----

    @patch("device_control.views.gemstone_client.is_configured", return_value=False)
    def test_states_not_configured(self, _cfg):
        resp = self.client.get(reverse("device_control_gemstone_states"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["configured"])
        self.assertEqual(data["devices"], [])
        self.assertEqual(data["patterns"], [])

    @patch("device_control.views.gemstone_client.get_states")
    @patch("device_control.views.gemstone_client.is_configured", return_value=True)
    def test_states_success(self, _cfg, mock_states):
        mock_states.return_value = {
            "devices": [self._device()],
            "patterns": [self._pattern()],
        }
        resp = self.client.get(reverse("device_control_gemstone_states"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["configured"])
        self.assertEqual(len(data["devices"]), 1)
        self.assertEqual(data["devices"][0]["id"], "dev-123")
        self.assertEqual(len(data["patterns"]), 1)
        self.assertEqual(data["patterns"][0]["id"], "pat-1")

    @patch("device_control.views.gemstone_client.get_states")
    @patch("device_control.views.gemstone_client.is_configured", return_value=True)
    def test_states_cloud_error_returns_502(self, _cfg, mock_states):
        mock_states.side_effect = views.gemstone_client.GemstoneError("cloud down")
        resp = self.client.get(reverse("device_control_gemstone_states"))
        self.assertEqual(resp.status_code, 502)
        data = resp.json()
        self.assertTrue(data["configured"])
        self.assertIn("error", data)

    # ----- action endpoint -----

    def test_action_requires_post(self):
        resp = self.client.get(reverse("device_control_gemstone_action"))
        self.assertEqual(resp.status_code, 405)

    def test_action_rejects_bad_json(self):
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_missing_device_id(self):
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"action": "power", "value": true}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_unknown_action(self):
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "explode", "value": true}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_bad_power_value(self):
        # power must be a bool
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "power", "value": "on"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_empty_pattern(self):
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "pattern", "value": ""}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("device_control.views.gemstone_client.is_configured", return_value=False)
    def test_action_not_configured_returns_503(self, _cfg):
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "power", "value": true}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 503)

    @patch("device_control.views.gemstone_client.apply_action")
    @patch("device_control.views.gemstone_client.is_configured", return_value=True)
    def test_action_power_success(self, _cfg, mock_apply):
        mock_apply.return_value = self._device(power=False)
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "power", "value": false}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["device"]["power"])
        mock_apply.assert_called_once_with("dev-123", "power", False)

    @patch("device_control.views.gemstone_client.apply_action")
    @patch("device_control.views.gemstone_client.is_configured", return_value=True)
    def test_action_pattern_success(self, _cfg, mock_apply):
        mock_apply.return_value = self._device(pattern_id="pat-2", pattern_name="Halloween")
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "pattern", "value": "pat-2"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        mock_apply.assert_called_once_with("dev-123", "pattern", "pat-2")

    @patch("device_control.views.gemstone_client.apply_action")
    @patch("device_control.views.gemstone_client.is_configured", return_value=True)
    def test_action_cloud_error_returns_502(self, _cfg, mock_apply):
        mock_apply.side_effect = views.gemstone_client.GemstoneError("timeout")
        resp = self.client.post(
            reverse("device_control_gemstone_action"),
            data='{"device_id": "dev-123", "action": "power", "value": true}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.json()["ok"])


class GemstoneTabTests(TestCase):
    """The gemstone tab must render its dedicated panel structure."""

    def test_gemstone_panel_rendered(self):
        resp = self.client.get(reverse("device_control"))
        content = resp.content.decode()
        self.assertIn('id="panel-gemstone"', content)
        self.assertIn('id="gemSelect"', content)
        self.assertIn('id="gemDetail"', content)
        self.assertIn('gemstone.js', content)
        self.assertIn('gemstone.css', content)


class GemstoneColorDecodeTests(TestCase):
    """``_color_to_hex`` must honour Gemstone's little-endian (R-low) packing."""

    def test_known_fixture_colors(self):
        from .gemstone_client import _color_to_hex
        # Values + names taken from pygemstone's own test fixtures.
        self.assertEqual(_color_to_hex(255), "#ff0000")        # "Red"  0x000000FF
        self.assertEqual(_color_to_hex(65280), "#00ff00")      # "Green" 0x0000FF00
        self.assertEqual(_color_to_hex(16711680), "#0000ff")   # blue   0x00FF0000
        self.assertEqual(_color_to_hex(16777215), "#ffffff")   # "Cool White" 0x00FFFFFF
        self.assertEqual(_color_to_hex(4294967295), "#ffffff")  # white w/ alpha

    def test_warm_white_channel(self):
        from .gemstone_client import _color_to_hex
        # White-LED channel sentinel (0xFF000000): no RGB, render warm white.
        self.assertEqual(_color_to_hex(4278190080), "#fff1e0")

    def test_bad_input_falls_back(self):
        from .gemstone_client import _color_to_hex
        self.assertEqual(_color_to_hex(None), "#000000")
        self.assertEqual(_color_to_hex("nope"), "#000000")


@tag('selenium')
class DeviceControlShadesSliderTest(StaticLiveServerTestCase):
    """Ensure shade cards render a position slider that fits within the card."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from selenium import webdriver
        from tests.selenium_helpers import get_chrome_options
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': 1920,
            'height': 1080,
            'deviceScaleFactor': 1,
            'mobile': False,
        })

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def test_shade_slider_visible(self):
        """Each shade card must contain a visible position slider."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        self.browser.get(self.live_server_url + reverse("device_control"))

        # Click the Shades tab
        WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "dc-tab"))
        )
        for tab_btn in self.browser.find_elements(By.CLASS_NAME, "dc-tab"):
            if "Shades" in tab_btn.text:
                tab_btn.click()
                break

        # Wait for shade cards to appear
        WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dc-cover-slider"))
        )

        # Check every shade card's slider
        cards = self.browser.find_elements(By.CSS_SELECTOR, "[data-type='cover']")
        self.assertTrue(len(cards) > 0, "No shade cards found")

        for card in cards:
            card_rect = card.rect
            card_right = card_rect['x'] + card_rect['width']

            sliders = card.find_elements(By.CSS_SELECTOR, ".dc-cover-slider")
            self.assertEqual(len(sliders), 1,
                             f"Expected 1 slider in card, found {len(sliders)}")

            slider = sliders[0]
            slider_rect = slider.rect
            slider_right = slider_rect['x'] + slider_rect['width']

            # Slider must not extend beyond the card
            self.assertLessEqual(
                slider_right, card_right + 1,
                f"Slider right edge ({slider_right}px) extends "
                f"beyond card right edge ({card_right}px)"
            )

            # Slider must have positive visible dimensions
            self.assertGreater(
                slider_rect['width'], 0,
                "Slider has zero width — not visible"
            )
            self.assertGreater(
                slider_rect['height'], 0,
                "Slider has zero height — not visible"
            )


class HomepageHookTests(TestCase):
    STATES = [
        {"entity_id": "climate.living", "state": "heat"},
        {"entity_id": "climate.bedroom", "state": "off"},
        {"entity_id": "climate.nest", "state": "heat"},
    ]

    def setUp(self):
        registry = {"entities": {"climate.living": {}, "climate.bedroom": {}, "switch.living": {}}}
        for target, value in [
            ("device_control.homepage._napoleon_registry", registry),
            ("device_control.homepage.get_all_states", self.STATES),
        ]:
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_status_counts_fireplaces(self):
        from device_control.homepage import status
        self.assertEqual(status().text, "1 of 2 fireplaces on")

    @patch("device_control.homepage.call_service", return_value=(True, None))
    def test_fireplaces_off_only_touches_lit_fireplaces(self, mock_call):
        from device_control.homepage import run_shortcut
        run_shortcut("fireplaces_off")
        mock_call.assert_called_once_with("climate", "turn_off", "climate.living")