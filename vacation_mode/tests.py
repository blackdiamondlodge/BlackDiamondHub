from django.test import TestCase, Client, tag
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from unittest.mock import patch, MagicMock
import json
import time
import unittest
import requests as requests_lib

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService

    # Try to use webdriver-manager for auto-matching chromedriver
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        _chrome_service = ChromeService(ChromeDriverManager().install())
    except ImportError:
        _chrome_service = None

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    _chrome_service = None

from .executor import (
    call_ha_service,
    execute_step,
    get_away_mode_state,
    get_current_season,
    start_execution,
    get_run_status,
    get_active_run,
    run_steps,
    verify_entity_state,
    _get_expected_state,
    _get_entity_ids_for_action,
    _runs,
    _execution_lock,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    STATUS_FAILED,
    MAX_RETRIES,
    RETRY_DELAY,
    SEASON_THRESHOLD_C,
)
from .steps import (
    VACATION_STEPS,
    HOME_STEPS,
    SEASON_HEATING,
    SEASON_COOLING,
    build_vacation_steps,
    build_home_steps,
)


class GetAwayModeStateTests(TestCase):
    """Tests for querying the away mode state from Home Assistant."""

    @patch("vacation_mode.executor.requests.get")
    def test_returns_true_when_on(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "on", "entity_id": "input_boolean.home_away_mode_enabled"},
        )
        self.assertTrue(get_away_mode_state())

    @patch("vacation_mode.executor.requests.get")
    def test_returns_false_when_off(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "off", "entity_id": "input_boolean.home_away_mode_enabled"},
        )
        self.assertFalse(get_away_mode_state())

    @patch("vacation_mode.executor.requests.get")
    def test_returns_false_on_error(self, mock_get):
        mock_get.side_effect = requests_lib.RequestException("Connection refused")
        self.assertFalse(get_away_mode_state())


class CallHaServiceTests(TestCase):
    """Tests for calling Home Assistant services."""

    @patch("vacation_mode.executor.requests.post")
    def test_successful_call(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        success, error = call_ha_service(
            action="input_boolean/turn_on",
            data={"entity_id": "input_boolean.home_away_mode_enabled"},
        )
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch("vacation_mode.executor.requests.post")
    def test_failed_call_returns_error(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
        success, error = call_ha_service(
            action="climate/set_temperature",
            data={"temperature": 13.5},
            device_id="abc123",
        )
        self.assertFalse(success)
        self.assertIn("500", error)

    @patch("vacation_mode.executor.requests.post")
    def test_network_exception(self, mock_post):
        mock_post.side_effect = requests_lib.ConnectionError("Connection timeout")
        success, error = call_ha_service(
            action="switch/turn_on",
            data={"entity_id": "switch.test"},
        )
        self.assertFalse(success)
        self.assertIn("Connection timeout", error)

    @patch("vacation_mode.executor.requests.post")
    def test_device_id_targeting(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        call_ha_service(
            action="climate/set_temperature",
            data={"entity_id": None, "temperature": 20},
            device_id="test_device",
        )
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertEqual(payload["device_id"], "test_device")
        self.assertNotIn("entity_id", payload)

    @patch("vacation_mode.executor.requests.post")
    def test_area_id_targeting(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        call_ha_service(
            action="climate/set_temperature",
            data={"temperature": 5},
            area_id=["garage", "garage_storage_room"],
        )
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertEqual(payload["area_id"], ["garage", "garage_storage_room"])

    @patch("vacation_mode.executor.requests.post")
    def test_entity_id_override(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        call_ha_service(
            action="switch/turn_on",
            data={"entity_id": None},
            device_id="some_device",
            entity_id_override="switch.specific_entity",
        )
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertEqual(payload["entity_id"], "switch.specific_entity")


class ExecuteStepTests(TestCase):
    """Tests for executing individual steps."""

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    def test_step_success(self, mock_call, mock_verify):
        mock_call.return_value = (True, None)
        step = {
            "alias": "Test Step",
            "actions": [
                {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}},
            ],
        }
        step_status = {"status": "running", "error": None}
        success, failed_indices = execute_step(step, step_status)
        self.assertTrue(success)
        self.assertEqual(failed_indices, set())
        mock_verify.assert_called_once()

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    def test_step_failure(self, mock_call, mock_verify):
        mock_call.return_value = (False, "Service unavailable")
        step = {
            "alias": "Test Step",
            "actions": [
                {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}},
            ],
        }
        step_status = {"status": "running", "error": None}
        success, failed_indices = execute_step(step, step_status)
        self.assertFalse(success)
        self.assertEqual(failed_indices, {0})
        self.assertIn("Service unavailable", step_status["error"])
        # verify_entity_state should NOT be called when service call fails
        mock_verify.assert_not_called()

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    def test_partial_action_failure(self, mock_call, mock_verify):
        """If one action in a step fails but others succeed, the step still fails."""
        mock_call.side_effect = [(True, None), (False, "Error"), (True, None)]
        step = {
            "alias": "Multi-action Step",
            "actions": [
                {"action": "switch/turn_on", "data": {"entity_id": "s1"}},
                {"action": "switch/turn_on", "data": {"entity_id": "s2"}},
                {"action": "switch/turn_on", "data": {"entity_id": "s3"}},
            ],
        }
        step_status = {"status": "running", "error": None}
        success, failed_indices = execute_step(step, step_status)
        self.assertFalse(success)
        self.assertEqual(failed_indices, {1})  # Only action index 1 failed
        # But all 3 actions were attempted (continue on sub-action failure)
        self.assertEqual(mock_call.call_count, 3)
        # verify_entity_state called for action 1 and 3 (succeeded), not 2 (failed)
        self.assertEqual(mock_verify.call_count, 2)

    @patch("vacation_mode.executor.verify_entity_state")
    @patch("vacation_mode.executor.call_ha_service")
    def test_step_fails_when_verification_fails(self, mock_call, mock_verify):
        """Step should fail if service call succeeds but state verification fails."""
        mock_call.return_value = (True, None)
        mock_verify.return_value = (False, "State verification failed: switch.test is unavailable")
        step = {
            "alias": "Test Step",
            "actions": [
                {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}},
            ],
        }
        step_status = {"status": "running", "error": None}
        success, failed_indices = execute_step(step, step_status)
        self.assertFalse(success)
        self.assertEqual(failed_indices, {0})
        self.assertIn("unavailable", step_status["error"])


class GetExpectedStateTests(TestCase):
    """Tests for _get_expected_state helper."""

    def test_switch_turn_on(self):
        check, expected = _get_expected_state("switch/turn_on", {})
        self.assertEqual(check, "state")
        self.assertEqual(expected, "on")

    def test_switch_turn_off(self):
        check, expected = _get_expected_state("switch/turn_off", {})
        self.assertEqual(check, "state")
        self.assertEqual(expected, "off")

    def test_input_boolean_turn_on(self):
        check, expected = _get_expected_state("input_boolean/turn_on", {})
        self.assertEqual(check, "state")
        self.assertEqual(expected, "on")

    def test_input_boolean_turn_off(self):
        check, expected = _get_expected_state("input_boolean/turn_off", {})
        self.assertEqual(check, "state")
        self.assertEqual(expected, "off")

    def test_climate_set_temperature(self):
        check, expected = _get_expected_state("climate/set_temperature", {"temperature": 13.5})
        self.assertEqual(check, "attr:temperature")
        self.assertEqual(expected, 13.5)

    def test_climate_set_preset_mode(self):
        check, expected = _get_expected_state("climate/set_preset_mode", {"preset_mode": "Off"})
        self.assertEqual(check, "attr:preset_mode")
        self.assertEqual(expected, "Off")

    def test_number_set_value(self):
        check, expected = _get_expected_state("number/set_value", {"value": "28"})
        self.assertEqual(check, "state_numeric")
        self.assertEqual(expected, 28.0)

    def test_unknown_action(self):
        check, expected = _get_expected_state("light/turn_on", {})
        self.assertEqual(check, "state")
        self.assertEqual(expected, "on")

    def test_climate_set_temperature_no_value(self):
        check, expected = _get_expected_state("climate/set_temperature", {})
        self.assertIsNone(check)
        self.assertIsNone(expected)


class GetEntityIdsForActionTests(TestCase):
    """Tests for _get_entity_ids_for_action helper."""

    def test_single_entity_id(self):
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        self.assertEqual(_get_entity_ids_for_action(action), ["switch.test"])

    def test_list_entity_ids(self):
        action = {"action": "climate/set_preset_mode", "data": {"entity_id": ["c1", "c2"]}}
        self.assertEqual(_get_entity_ids_for_action(action), ["c1", "c2"])

    def test_entity_id_override(self):
        action = {"action": "switch/turn_on", "data": {}, "entity_id_override": "switch.override"}
        self.assertEqual(_get_entity_ids_for_action(action), ["switch.override"])

    def test_device_id_only(self):
        action = {"action": "switch/turn_on", "data": {}, "device_id": "abc123"}
        self.assertEqual(_get_entity_ids_for_action(action), [])

    def test_no_targeting(self):
        action = {"action": "switch/turn_on", "data": {}}
        self.assertEqual(_get_entity_ids_for_action(action), [])


class VerifyEntityStateTests(TestCase):
    """Tests for verify_entity_state."""

    def test_dry_run_skips_verification(self):
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action, dry_run=True)
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_switch_on_verified(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "on", "attributes": {}},
        )
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_switch_still_off_after_turn_on(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "off", "attributes": {}},
        )
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("expected state 'on', got 'off'", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_entity_unavailable(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "unavailable", "attributes": {}},
        )
        action = {"action": "switch/turn_off", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("is unavailable", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_entity_unknown(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "unknown", "attributes": {}},
        )
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("is unknown", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_climate_temperature_verified(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "heat", "attributes": {"temperature": 13.5}},
        )
        action = {"action": "climate/set_temperature", "data": {"entity_id": "climate.main_floor", "temperature": 13.5}}
        success, error = verify_entity_state(action)
        self.assertTrue(success)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_climate_temperature_wrong(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "heat", "attributes": {"temperature": 20.0}},
        )
        action = {"action": "climate/set_temperature", "data": {"entity_id": "climate.main_floor", "temperature": 13.5}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("expected temperature~=13.5, got 20.0", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_climate_preset_mode_verified(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "heat", "attributes": {"preset_mode": "Off"}},
        )
        action = {"action": "climate/set_preset_mode", "data": {"entity_id": "climate.econet_hpwh", "preset_mode": "Off"}}
        success, error = verify_entity_state(action)
        self.assertTrue(success)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_climate_preset_mode_wrong(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "heat", "attributes": {"preset_mode": "Eco Mode"}},
        )
        action = {"action": "climate/set_preset_mode", "data": {"entity_id": "climate.econet_hpwh", "preset_mode": "Off"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("expected preset_mode='Off', got 'Eco Mode'", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_number_set_value_verified(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "28", "attributes": {}},
        )
        action = {"action": "number/set_value", "data": {"entity_id": "number.buffer_tank", "value": "28"}}
        success, error = verify_entity_state(action)
        self.assertTrue(success)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_number_set_value_within_tolerance(self, mock_get):
        """Values within C/F rounding tolerance (0.5) should pass verification."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"state": "37.8", "attributes": {}},
        )
        action = {"action": "number/set_value", "data": {"entity_id": "number.buffer_tank", "value": "38"}}
        success, error = verify_entity_state(action)
        self.assertTrue(success)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_multiple_entities_one_fails(self, mock_get):
        """When multiple entity_ids given, failure of one should fail the verification."""
        def mock_responses(*args, **kwargs):
            url = args[0]
            if "climate.ok" in url:
                return MagicMock(status_code=200, json=lambda: {"state": "heat", "attributes": {"preset_mode": "none"}})
            else:
                return MagicMock(status_code=200, json=lambda: {"state": "unavailable", "attributes": {}})
        mock_get.side_effect = mock_responses
        action = {"action": "climate/set_preset_mode", "data": {"entity_id": ["climate.ok", "climate.dead"], "preset_mode": "none"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("climate.dead is unavailable", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_http_error_on_state_query(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("HTTP 500", error)

    @patch("vacation_mode.executor.STATE_VERIFY_DELAY", 0)
    @patch("vacation_mode.executor.requests.get")
    def test_network_error_on_state_query(self, mock_get):
        mock_get.side_effect = requests_lib.ConnectionError("timeout")
        action = {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}}
        success, error = verify_entity_state(action)
        self.assertFalse(success)
        self.assertIn("state query failed", error)

    def test_no_entity_id_skips_verification(self):
        """Actions with device_id only can't be verified."""
        action = {"action": "switch/turn_on", "data": {}, "device_id": "abc123"}
        success, error = verify_entity_state(action)
        self.assertTrue(success)


def _make_owner(username="owner"):
    from django.contrib.auth.models import User
    return User.objects.create_user(username, password="pw")


class ViewTests(TestCase):
    """Tests for the vacation mode views."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(_make_owner())
        p = patch(
            "vacation_mode.views.get_current_season",
            return_value=("heating", 5.0),
        )
        self.mock_season = p.start()
        self.addCleanup(p.stop)

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_loads(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vacation Mode")

    @patch("vacation_mode.views.start_execution")
    def test_execute_returns_run_id(self, mock_start):
        mock_start.return_value = ("abc123", None)
        response = self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "vacation"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_id"], "abc123")

    def test_execute_invalid_mode(self):
        response = self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "invalid"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("vacation_mode.views.start_execution")
    def test_execute_already_running(self, mock_start):
        mock_start.return_value = (None, "An execution is already in progress")
        response = self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "vacation"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_status_not_found(self):
        response = self.client.get("/vacation_mode/api/status/nonexistent/")
        self.assertEqual(response.status_code, 404)

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_state_endpoint(self, mock_active, mock_away):
        mock_away.return_value = True
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/api/state/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_away"])
        self.assertIsNone(data["active_run"])


class DryRunTests(TestCase):
    """Tests for dry run mode."""

    @patch("vacation_mode.executor.requests.post")
    def test_dry_run_skips_api_call(self, mock_post):
        """Dry run should not make any HTTP requests."""
        success, error = call_ha_service(
            action="switch/turn_on",
            data={"entity_id": "switch.test"},
            dry_run=True,
        )
        self.assertTrue(success)
        self.assertIsNone(error)
        mock_post.assert_not_called()

    @patch("vacation_mode.executor.requests.post")
    def test_dry_run_execute_step(self, mock_post):
        """Dry run step should succeed without HTTP calls."""
        step = {
            "alias": "Test Step",
            "actions": [
                {"action": "switch/turn_on", "data": {"entity_id": "switch.test"}},
                {"action": "switch/turn_off", "data": {"entity_id": "switch.test2"}},
            ],
        }
        step_status = {"status": "running", "error": None}
        success, failed_indices = execute_step(step, step_status, dry_run=True)
        self.assertTrue(success)
        self.assertEqual(failed_indices, set())
        mock_post.assert_not_called()

    @patch("vacation_mode.views.start_execution")
    def test_execute_passes_dry_run(self, mock_start):
        """Execute view should pass dry_run to start_execution."""
        mock_start.return_value = ("abc123", None)
        client = Client()
        client.force_login(_make_owner())
        response = client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "vacation", "dry_run": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mock_start.assert_called_once_with("vacation", dry_run=True, skip_steps=[])


class StepDefinitionTests(TestCase):
    """Tests to validate step definitions are well-formed."""

    def test_vacation_steps_not_empty(self):
        self.assertGreater(len(VACATION_STEPS), 0)

    def test_home_steps_not_empty(self):
        self.assertGreater(len(HOME_STEPS), 0)

    def test_all_vacation_steps_have_required_fields(self):
        for i, step in enumerate(VACATION_STEPS):
            with self.subTest(step=i, alias=step.get("alias")):
                self.assertIn("alias", step)
                self.assertIn("icon", step)
                self.assertIn("actions", step)
                self.assertIsInstance(step["actions"], list)
                self.assertGreater(len(step["actions"]), 0)

    def test_all_home_steps_have_required_fields(self):
        for i, step in enumerate(HOME_STEPS):
            with self.subTest(step=i, alias=step.get("alias")):
                self.assertIn("alias", step)
                self.assertIn("icon", step)
                self.assertIn("actions", step)
                self.assertIsInstance(step["actions"], list)
                self.assertGreater(len(step["actions"]), 0)

    def test_all_actions_have_action_field(self):
        """Every action must have a 'domain/service' format action field."""
        all_steps = VACATION_STEPS + HOME_STEPS
        for step in all_steps:
            for j, action in enumerate(step["actions"]):
                with self.subTest(step=step["alias"], action=j):
                    self.assertIn("action", action)
                    self.assertIn("/", action["action"], "Action must be 'domain/service' format")

    def test_all_actions_have_data(self):
        """Every action must have a data dict."""
        all_steps = VACATION_STEPS + HOME_STEPS
        for step in all_steps:
            for j, action in enumerate(step["actions"]):
                with self.subTest(step=step["alias"], action=j):
                    self.assertIn("data", action)
                    self.assertIsInstance(action["data"], dict)

    def test_all_actions_have_targeting(self):
        """Every action must have at least one targeting method."""
        all_steps = VACATION_STEPS + HOME_STEPS
        for step in all_steps:
            for j, action in enumerate(step["actions"]):
                with self.subTest(step=step["alias"], action=j):
                    has_entity = action["data"].get("entity_id") is not None
                    has_device = action.get("device_id") is not None
                    has_area = action.get("area_id") is not None
                    has_override = action.get("entity_id_override") is not None
                    self.assertTrue(
                        has_entity or has_device or has_area or has_override,
                        f"Action has no targeting (entity_id, device_id, area_id, or entity_id_override)"
                    )

    def test_icons_are_font_awesome(self):
        """All step icons should be Font Awesome classes."""
        all_steps = VACATION_STEPS + HOME_STEPS
        for step in all_steps:
            with self.subTest(step=step["alias"]):
                self.assertTrue(
                    step["icon"].startswith("fas ") or step["icon"].startswith("fab "),
                    f"Icon '{step['icon']}' doesn't look like a Font Awesome class"
                )


class RunStepsTests(TestCase):
    """Tests for the full run_steps execution flow."""

    def setUp(self):
        # Ensure lock is released before each test
        if _execution_lock.locked():
            _execution_lock.release()

    def tearDown(self):
        # Clean up
        if _execution_lock.locked():
            _execution_lock.release()
        _runs.clear()

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    def test_all_steps_succeed(self, mock_call, mock_verify):
        mock_call.return_value = (True, None)

        steps = [
            {"alias": "Step 1", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s1"}}]},
            {"alias": "Step 2", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s2"}}]},
        ]

        run_id = "test-run-1"
        _execution_lock.acquire()
        _runs[run_id] = {
            "run_id": run_id, "mode": "vacation", "status": "running",
            "steps": [{"alias": s["alias"], "icon": s["icon"], "status": STATUS_PENDING, "attempt": 0, "error": None} for s in steps],
        }

        run_steps(run_id, steps)

        run_data = _runs[run_id]
        self.assertEqual(run_data["status"], "complete")
        for step in run_data["steps"]:
            self.assertEqual(step["status"], STATUS_SUCCESS)

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    @patch("vacation_mode.executor.RETRY_DELAY", 0)
    def test_step_retries_then_succeeds(self, mock_call, mock_verify):
        """A step that fails once then succeeds on retry."""
        mock_call.side_effect = [(False, "timeout"), (True, None)]

        steps = [
            {"alias": "Flaky Step", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s1"}}]},
        ]

        run_id = "test-run-2"
        _execution_lock.acquire()
        _runs[run_id] = {
            "run_id": run_id, "mode": "vacation", "status": "running",
            "steps": [{"alias": "Flaky Step", "icon": "fas fa-test", "status": STATUS_PENDING, "attempt": 0, "error": None}],
        }

        run_steps(run_id, steps)

        run_data = _runs[run_id]
        self.assertEqual(run_data["steps"][0]["status"], STATUS_SUCCESS)
        self.assertEqual(run_data["status"], "complete")

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    @patch("vacation_mode.executor.RETRY_DELAY", 0)
    def test_step_fails_all_retries_then_continues(self, mock_call, mock_verify):
        """A step that fails all retries — the run should still complete (continue past it)."""
        # First step always fails, second step succeeds
        mock_call.side_effect = [
            (False, "error")] * (1 + MAX_RETRIES) + [(True, None)
        ]

        steps = [
            {"alias": "Bad Step", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s1"}}]},
            {"alias": "Good Step", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s2"}}]},
        ]

        run_id = "test-run-3"
        _execution_lock.acquire()
        _runs[run_id] = {
            "run_id": run_id, "mode": "vacation", "status": "running",
            "steps": [
                {"alias": "Bad Step", "icon": "fas fa-test", "status": STATUS_PENDING, "attempt": 0, "error": None},
                {"alias": "Good Step", "icon": "fas fa-test", "status": STATUS_PENDING, "attempt": 0, "error": None},
            ],
        }

        run_steps(run_id, steps)

        run_data = _runs[run_id]
        self.assertEqual(run_data["status"], "complete")
        self.assertEqual(run_data["steps"][0]["status"], STATUS_FAILED)
        self.assertEqual(run_data["steps"][1]["status"], STATUS_SUCCESS)

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    @patch("vacation_mode.executor.RETRY_DELAY", 0)
    def test_retry_only_reruns_failed_actions(self, mock_call, mock_verify):
        """On retry, only the failed actions should be re-executed, not the whole step."""
        # 3 actions: first succeeds, second fails, third succeeds → retry second → succeeds
        mock_call.side_effect = [
            (True, None),   # action 0: succeeds
            (False, "err"), # action 1: fails
            (True, None),   # action 2: succeeds
            (True, None),   # retry action 1: succeeds
        ]

        steps = [
            {
                "alias": "Multi Step",
                "icon": "fas fa-test",
                "actions": [
                    {"action": "switch/turn_on", "data": {"entity_id": "s1"}},
                    {"action": "switch/turn_on", "data": {"entity_id": "s2"}},
                    {"action": "switch/turn_on", "data": {"entity_id": "s3"}},
                ],
            },
        ]

        run_id = "test-run-retry-partial"
        _execution_lock.acquire()
        _runs[run_id] = {
            "run_id": run_id, "mode": "home", "status": "running",
            "steps": [{"alias": "Multi Step", "icon": "fas fa-test", "status": STATUS_PENDING, "attempt": 0, "error": None, "progress": None}],
        }

        run_steps(run_id, steps)

        run_data = _runs[run_id]
        self.assertEqual(run_data["steps"][0]["status"], STATUS_SUCCESS)
        # Total calls: 3 initial + 1 retry = 4 (NOT 3 initial + 3 retry = 6)
        self.assertEqual(mock_call.call_count, 4)
        # verify called for: action 0, action 2 (initial) + action 1 (retry) = 3
        self.assertEqual(mock_verify.call_count, 3)

    @patch("vacation_mode.executor.verify_entity_state", return_value=(True, None))
    @patch("vacation_mode.executor.call_ha_service")
    def test_run_releases_lock_on_completion(self, mock_call, mock_verify):
        mock_call.return_value = (True, None)
        steps = [{"alias": "S", "icon": "fas fa-test", "actions": [{"action": "switch/turn_on", "data": {"entity_id": "s1"}}]}]

        run_id = "test-run-4"
        _execution_lock.acquire()
        _runs[run_id] = {
            "run_id": run_id, "mode": "vacation", "status": "running",
            "steps": [{"alias": "S", "icon": "fas fa-test", "status": STATUS_PENDING, "attempt": 0, "error": None}],
        }

        run_steps(run_id, steps)
        # Lock should be released — we can acquire it again
        acquired = _execution_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        if acquired:
            _execution_lock.release()


class StartExecutionTests(TestCase):
    """Tests for the start_execution function."""

    def setUp(self):
        if _execution_lock.locked():
            _execution_lock.release()
        _runs.clear()
        # Avoid a live HA call for the season decision.
        p = patch(
            "vacation_mode.executor.get_current_season",
            return_value=("heating", 5.0),
        )
        self.mock_season = p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        # Wait for any background threads to finish
        time.sleep(0.2)
        if _execution_lock.locked():
            _execution_lock.release()
        _runs.clear()

    @patch("vacation_mode.executor.call_ha_service")
    def test_start_vacation_mode(self, mock_call):
        mock_call.return_value = (True, None)
        run_id, error = start_execution("vacation", dry_run=True)
        self.assertIsNotNone(run_id)
        self.assertIsNone(error)

    @patch("vacation_mode.executor.call_ha_service")
    def test_start_home_mode(self, mock_call):
        mock_call.return_value = (True, None)
        run_id, error = start_execution("home", dry_run=True)
        self.assertIsNotNone(run_id)
        self.assertIsNone(error)

    @patch("vacation_mode.executor.call_ha_service")
    def test_concurrent_execution_blocked(self, mock_call):
        """Cannot start a second execution while one is running."""
        # Simulate a long-running step
        def slow_call(*args, **kwargs):
            time.sleep(2)
            return True, None
        mock_call.side_effect = slow_call

        run_id1, error1 = start_execution("vacation", dry_run=True)
        self.assertIsNotNone(run_id1)
        self.assertIsNone(error1)

        # Try to start another — should fail
        run_id2, error2 = start_execution("home", dry_run=True)
        self.assertIsNone(run_id2)
        self.assertIn("already in progress", error2)

    @patch("vacation_mode.executor.call_ha_service")
    def test_run_stores_dry_run_flag(self, mock_call):
        mock_call.return_value = (True, None)
        run_id, _ = start_execution("vacation", dry_run=True)
        self.assertTrue(_runs[run_id]["dry_run"])

    @patch("vacation_mode.executor.call_ha_service")
    def test_run_status_has_all_steps(self, mock_call):
        mock_call.return_value = (True, None)
        run_id, _ = start_execution("vacation", dry_run=True)
        status = get_run_status(run_id)
        self.assertIsNotNone(status)
        self.assertEqual(len(status["steps"]), len(VACATION_STEPS))


class AdditionalViewTests(TestCase):
    """Additional view tests for edge cases."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(_make_owner())
        p = patch(
            "vacation_mode.views.get_current_season",
            return_value=("heating", 5.0),
        )
        self.mock_season = p.start()
        self.addCleanup(p.stop)

    def test_execute_get_not_allowed(self):
        """Execute endpoint should reject GET requests."""
        response = self.client.get("/vacation_mode/api/execute/")
        self.assertEqual(response.status_code, 405)

    def test_execute_empty_body(self):
        """Execute with empty body should return 400."""
        response = self.client.post(
            "/vacation_mode/api/execute/",
            data="",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_execute_no_mode(self):
        """Execute without mode field should return 400."""
        response = self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_status_post_not_allowed(self):
        """Status endpoint should reject POST requests."""
        response = self.client.post("/vacation_mode/api/status/test/")
        self.assertEqual(response.status_code, 405)

    def test_state_post_not_allowed(self):
        """State endpoint should reject POST requests."""
        response = self.client.post("/vacation_mode/api/state/")
        self.assertEqual(response.status_code, 405)

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_vacation_mode_context(self, mock_active, mock_away):
        """When home, mode should be vacation (button to leave)."""
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertEqual(response.context["mode"], "vacation")
        self.assertFalse(response.context["is_away"])

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_home_mode_context(self, mock_active, mock_away):
        """When away, mode should be home (button to arrive)."""
        mock_away.return_value = True
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertEqual(response.context["mode"], "home")
        self.assertTrue(response.context["is_away"])

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_contains_step_json(self, mock_active, mock_away):
        """The page should contain JSON step data."""
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        content = response.content.decode()
        # Steps JSON should be embedded in the page
        self.assertIn("pending", content)

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_shows_vacation_button_when_home(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, "Put Black Diamond Lodge into Vacation Mode")

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_main_page_shows_arrival_button_when_away(self, mock_active, mock_away):
        mock_away.return_value = True
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, "Prepare Black Diamond Lodge for Arrival")

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_dry_run_checkbox_unchecked_by_default(self, mock_active, mock_away):
        """Dry run checkbox should be unchecked by default."""
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        content = response.content.decode()
        self.assertNotIn('checked', content.split('dry-run-checkbox')[1].split('>')[0])
        self.assertIn('let dryRun = false', content)

    @patch("vacation_mode.views.start_execution")
    def test_execute_dry_run_false_by_default(self, mock_start):
        """Without dry_run in body, it should default to False."""
        mock_start.return_value = ("abc123", None)
        self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "vacation"}),
            content_type="application/json",
        )
        mock_start.assert_called_once_with("vacation", dry_run=False, skip_steps=[])


class TemplateRenderTests(TestCase):
    """Tests for template rendering correctness."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(_make_owner())
        p = patch(
            "vacation_mode.views.get_current_season",
            return_value=("heating", 5.0),
        )
        self.mock_season = p.start()
        self.addCleanup(p.stop)

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_template_has_step_list(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, 'id="step-list"')

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_template_has_progress_bar(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, 'id="progress-container"')
        self.assertContains(response, 'id="progress-bar"')

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_template_has_status_badge(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, 'id="status-badge"')

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_away_badge_class(self, mock_active, mock_away):
        mock_away.return_value = True
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, "status-badge away")

    @patch("vacation_mode.views.get_away_mode_state")
    @patch("vacation_mode.views.get_active_run")
    def test_home_badge_class(self, mock_active, mock_away):
        mock_away.return_value = False
        mock_active.return_value = None
        response = self.client.get("/vacation_mode/")
        self.assertContains(response, "status-badge home")


class HomepageIconTests(TestCase):
    """The vacation mode icon is shown on the homepage only to logged-in users."""

    def setUp(self):
        self.client = Client()
        patcher = patch("BlackDiamondHub.views.requests.get")
        mock_get = patcher.start()
        self.addCleanup(patcher.stop)
        mock_response = MagicMock(status_code=200)
        mock_response.content = b'<div class="weather current-conditions"><ul class="list-temps"></ul></div>'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

    def test_homepage_shows_vacation_icon_when_logged_in(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user("owner", password="pw")
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertContains(response, 'href="/vacation_mode/"')
        self.assertContains(response, "vacation_mode/hub/icon.svg")
        self.assertContains(response, "Vacation Mode")

    def test_homepage_hides_vacation_icon_when_logged_out(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/vacation_mode/"')
        self.assertNotContains(response, "vacation_mode/hub/icon.svg")
        # Radiant stays public.
        self.assertContains(response, "/radiant/")


@tag('selenium')
class SeleniumVacationModeTests(StaticLiveServerTestCase):
    """Selenium tests to validate the vacation mode page renders correctly at 1920x1080."""

    _original_get_away_mode_state = None

    @classmethod
    def setUpClass(cls):
        if not SELENIUM_AVAILABLE:
            raise unittest.SkipTest("Selenium not available")
        super().setUpClass()
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-shm-usage")
        try:
            if _chrome_service:
                cls.driver = webdriver.Chrome(service=_chrome_service, options=chrome_options)
            else:
                cls.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            raise unittest.SkipTest(f"Chrome WebDriver not available: {e}")
        cls.driver.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        # Reset browser state between tests
        self.driver.get('about:blank')
        self.driver.delete_all_cookies()
        # The page is owner-only: log in by planting a session cookie.
        client = Client()
        client.force_login(_make_owner())
        self.driver.get(self.live_server_url)
        self.driver.add_cookie({
            "name": "sessionid",
            "value": client.cookies["sessionid"].value,
            "path": "/",
        })
        # Monkeypatch get_away_mode_state so the live server uses our mock
        from vacation_mode import views as vm_views
        self._original_get_away_mode_state = vm_views.get_away_mode_state
        vm_views.get_away_mode_state = lambda: False
        # Avoid a live HA call for the season decision
        self._original_get_current_season = vm_views.get_current_season
        vm_views.get_current_season = lambda: ("heating", 5.0)

    def tearDown(self):
        from vacation_mode import views as vm_views
        vm_views.get_away_mode_state = self._original_get_away_mode_state
        vm_views.get_current_season = self._original_get_current_season

    def _set_away_state(self, is_away):
        from vacation_mode import views as vm_views
        vm_views.get_away_mode_state = lambda: is_away

    def test_no_vertical_scrollbar_at_1080p(self):
        """Page should fit within 1920x1080 without vertical scrollbar."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "step-list"))
        )
        scroll_height = self.driver.execute_script("return document.documentElement.scrollHeight")
        client_height = self.driver.execute_script("return document.documentElement.clientHeight")
        self.assertLessEqual(
            scroll_height, client_height,
            f"Page has vertical scrollbar: scrollHeight={scroll_height} > clientHeight={client_height}"
        )

    def test_no_horizontal_scrollbar_at_1080p(self):
        """Page should fit within 1920x1080 without horizontal scrollbar."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "step-list"))
        )
        scroll_width = self.driver.execute_script("return document.documentElement.scrollWidth")
        client_width = self.driver.execute_script("return document.documentElement.clientWidth")
        self.assertLessEqual(
            scroll_width, client_width,
            f"Page has horizontal scrollbar: scrollWidth={scroll_width} > clientWidth={client_width}"
        )

    def test_step_items_render_on_page(self):
        """Step items should be rendered on the page."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "step-list"))
        )
        step_items = self.driver.find_elements(By.CSS_SELECTOR, ".step-item")
        self.assertEqual(len(step_items), len(VACATION_STEPS))

    def test_home_steps_render_when_away(self):
        """When away, home steps should be shown."""
        self._set_away_state(True)
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "step-list"))
        )
        step_items = self.driver.find_elements(By.CSS_SELECTOR, ".step-item")
        self.assertEqual(len(step_items), len(HOME_STEPS))

    def test_step_items_are_single_line(self):
        """Each step item should be a single-line row (no wrapping)."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "step-list"))
        )
        step_items = self.driver.find_elements(By.CSS_SELECTOR, ".step-item")
        for item in step_items:
            height = item.size["height"]
            # A single-line row with padding should be under 65px
            self.assertLessEqual(height, 65, f"Step item too tall ({height}px), may be wrapping")

    def test_action_button_visible(self):
        """The action button should be visible."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        btn = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "action-btn"))
        )
        self.assertTrue(btn.is_displayed())
        self.assertIn("Activate", btn.text)

    def test_action_label_shows_vacation_when_home(self):
        """When home, label should describe vacation mode action."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        label = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "action-label"))
        )
        self.assertIn("Put Black Diamond Lodge into Vacation Mode", label.text)

    def test_action_label_shows_arrival_when_away(self):
        """When away, label should describe arrival action."""
        self._set_away_state(True)
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        label = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "action-label"))
        )
        self.assertIn("Prepare Black Diamond Lodge for Arrival", label.text)

    def test_dry_run_unchecked_by_default(self):
        """Dry run checkbox should be unchecked by default."""
        self.driver.get(f"{self.live_server_url}/vacation_mode/")
        checkbox = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "dry-run-checkbox"))
        )
        self.assertFalse(checkbox.is_selected())


def _all_actions(steps):
    """Flatten every action across a list of steps."""
    actions = []
    for step in steps:
        actions.extend(step["actions"])
    return actions


def _entity_ids(steps):
    """Collect every entity_id referenced across a list of steps (flattened)."""
    ids = set()
    for action in _all_actions(steps):
        ent = action.get("data", {}).get("entity_id")
        if isinstance(ent, list):
            ids.update(ent)
        elif ent:
            ids.add(ent)
    return ids


class GetCurrentSeasonTests(TestCase):
    """Tests for executor.get_current_season season selection."""

    def _mock_response(self, status_code=200, state="20.0"):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = {"state": state}
        return resp

    @patch("vacation_mode.executor.requests.get")
    def test_warm_avg_selects_cooling(self, mock_get):
        mock_get.return_value = self._mock_response(state="20.0")
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_COOLING)
        self.assertEqual(avg, 20.0)

    @patch("vacation_mode.executor.requests.get")
    def test_cold_avg_selects_heating(self, mock_get):
        mock_get.return_value = self._mock_response(state="5.0")
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_HEATING)
        self.assertEqual(avg, 5.0)

    @patch("vacation_mode.executor.requests.get")
    def test_threshold_boundary_selects_cooling(self, mock_get):
        """At exactly the threshold we cool (>= threshold)."""
        mock_get.return_value = self._mock_response(state=str(SEASON_THRESHOLD_C))
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_COOLING)
        self.assertEqual(avg, SEASON_THRESHOLD_C)

    @patch("vacation_mode.executor.requests.get")
    def test_just_below_threshold_selects_heating(self, mock_get):
        mock_get.return_value = self._mock_response(state=str(SEASON_THRESHOLD_C - 0.1))
        season, _ = get_current_season()
        self.assertEqual(season, SEASON_HEATING)

    @patch("vacation_mode.executor.requests.get")
    def test_http_error_defaults_to_heating(self, mock_get):
        mock_get.return_value = self._mock_response(status_code=500)
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_HEATING)
        self.assertIsNone(avg)

    @patch("vacation_mode.executor.requests.get")
    def test_unparseable_state_defaults_to_heating(self, mock_get):
        mock_get.return_value = self._mock_response(state="unavailable")
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_HEATING)
        self.assertIsNone(avg)

    @patch("vacation_mode.executor.requests.get")
    def test_request_exception_defaults_to_heating(self, mock_get):
        mock_get.side_effect = requests_lib.RequestException("boom")
        season, avg = get_current_season()
        self.assertEqual(season, SEASON_HEATING)
        self.assertIsNone(avg)


class SeasonStepBuilderTests(TestCase):
    """Tests for the season-aware step builders in steps.py."""

    def test_heating_builders_match_module_defaults(self):
        """Module-level constants must equal the heating variant (back-compat)."""
        self.assertEqual(build_vacation_steps(SEASON_HEATING), VACATION_STEPS)
        self.assertEqual(build_home_steps(SEASON_HEATING), HOME_STEPS)

    def test_step_counts_match_across_seasons(self):
        """Cooling must yield the same step count as heating (test invariant)."""
        self.assertEqual(
            len(build_vacation_steps(SEASON_COOLING)),
            len(build_vacation_steps(SEASON_HEATING)),
        )
        self.assertEqual(
            len(build_home_steps(SEASON_COOLING)),
            len(build_home_steps(SEASON_HEATING)),
        )

    def test_vacation_step_count_is_ten(self):
        self.assertEqual(len(build_vacation_steps(SEASON_HEATING)), 10)

    def test_home_step_count_is_seven(self):
        self.assertEqual(len(build_home_steps(SEASON_HEATING)), 7)

    def test_heating_writes_hot_tank_not_cold(self):
        ids = _entity_ids(build_vacation_steps(SEASON_HEATING))
        self.assertTrue(any("hot_tank" in e for e in ids))
        self.assertFalse(any("cold_tank" in e for e in ids))

    def test_cooling_writes_cold_tank_not_hot(self):
        ids = _entity_ids(build_vacation_steps(SEASON_COOLING))
        self.assertTrue(any("cold_tank" in e for e in ids))
        self.assertFalse(any("hot_tank" in e for e in ids))

    def test_heating_sets_permanent_heat_demand_on(self):
        actions = _all_actions(build_vacation_steps(SEASON_HEATING))
        on_heat = [
            a for a in actions
            if a["action"] == "switch/turn_on"
            and a["data"].get("entity_id") == "switch.aeco_1988_permanent_heat_demand"
        ]
        off_cool = [
            a for a in actions
            if a["action"] == "switch/turn_off"
            and a["data"].get("entity_id") == "switch.aeco_1988_permanent_cool_demand"
        ]
        self.assertEqual(len(on_heat), 1)
        self.assertEqual(len(off_cool), 1)

    def test_cooling_sets_permanent_cool_demand_on(self):
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        on_cool = [
            a for a in actions
            if a["action"] == "switch/turn_on"
            and a["data"].get("entity_id") == "switch.aeco_1988_permanent_cool_demand"
        ]
        off_heat = [
            a for a in actions
            if a["action"] == "switch/turn_off"
            and a["data"].get("entity_id") == "switch.aeco_1988_permanent_heat_demand"
        ]
        self.assertEqual(len(on_cool), 1)
        self.assertEqual(len(off_heat), 1)

    def test_changeover_precedes_tank_writes(self):
        """The demand-on switch must be flipped before any tank number write."""
        for season, tank in (
            (SEASON_HEATING, "hot_tank"),
            (SEASON_COOLING, "cold_tank"),
        ):
            steps = build_vacation_steps(season)
            # find the heat-pump setup step (has the changeover switches)
            hp_step = next(
                s for s in steps
                if any(
                    "permanent_" in a["data"].get("entity_id", "")
                    for a in s["actions"]
                )
            )
            demand_on = "permanent_cool_demand" if season == SEASON_COOLING else "permanent_heat_demand"
            actions = hp_step["actions"]
            on_idx = next(
                i for i, a in enumerate(actions)
                if a["action"] == "switch/turn_on"
                and demand_on in a["data"].get("entity_id", "")
            )
            tank_idx = next(
                i for i, a in enumerate(actions)
                if tank in a["data"].get("entity_id", "")
            )
            self.assertLess(on_idx, tank_idx, f"{season}: changeover must precede tank write")

    def test_changeover_settle_delay(self):
        """The demand-on flip must wait MODE_SWITCH_DELAY before tank writes."""
        from vacation_mode.steps import MODE_SWITCH_DELAY
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        on_cool = next(
            a for a in actions
            if a["action"] == "switch/turn_on"
            and a["data"].get("entity_id") == "switch.aeco_1988_permanent_cool_demand"
        )
        self.assertEqual(on_cool.get("delay_after"), MODE_SWITCH_DELAY)

    def test_cooling_thermostats_use_cool_mode(self):
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        set_temp = [a for a in actions if a["action"] == "climate/set_temperature"
                    and a["data"].get("entity_id", "").startswith("climate.")
                    and "hvac_mode" in a["data"]]
        self.assertTrue(set_temp)
        self.assertTrue(all(a["data"]["hvac_mode"] == "cool" for a in set_temp))

    def test_heating_thermostats_use_heat_mode(self):
        actions = _all_actions(build_vacation_steps(SEASON_HEATING))
        set_temp = [a for a in actions if a["action"] == "climate/set_temperature"
                    and "hvac_mode" in a["data"]]
        self.assertTrue(set_temp)
        self.assertTrue(all(a["data"]["hvac_mode"] == "heat" for a in set_temp))

    def test_cooling_away_thermostat_setpoint(self):
        """Away/cooling zones target 28°C."""
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        zone_sets = [
            a for a in actions
            if a["action"] == "climate/set_temperature"
            and a["data"].get("hvac_mode") == "cool"
        ]
        self.assertTrue(zone_sets)
        self.assertTrue(all(a["data"]["temperature"] == 28 for a in zone_sets))

    def test_cooling_home_thermostat_setpoint(self):
        """Home/cooling zones target 22°C."""
        actions = _all_actions(build_home_steps(SEASON_COOLING))
        zone_sets = [
            a for a in actions
            if a["action"] == "climate/set_temperature"
            and a["data"].get("hvac_mode") == "cool"
        ]
        self.assertTrue(zone_sets)
        self.assertTrue(all(a["data"]["temperature"] == 22 for a in zone_sets))

    def test_nest_thermostats_set_individually(self):
        """Each Nest zone is its own action (rate-limited, never batched)."""
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        zone_sets = [
            a for a in actions
            if a["action"] == "climate/set_temperature"
            and a["data"].get("hvac_mode") == "cool"
        ]
        for a in zone_sets:
            self.assertNotIsInstance(
                a["data"]["entity_id"], list,
                "Nest thermostats must be set one entity at a time",
            )

    def test_cooling_home_cold_tank_values(self):
        actions = _all_actions(build_home_steps(SEASON_COOLING))
        by_ent = {
            a["data"]["entity_id"]: a["data"]["value"]
            for a in actions if a["action"] == "number/set_value"
        }
        self.assertEqual(by_ent["number.aeco_1988_cold_tank_target_temperature"], "14.4")
        # Fixed target only: min/max are unavailable while reset is off, so we
        # must NOT attempt to write them.
        self.assertNotIn("number.aeco_1988_cold_tank_min_temperature", by_ent)
        self.assertNotIn("number.aeco_1988_cold_tank_max_temperature", by_ent)

    def test_cooling_away_cold_tank_values(self):
        actions = _all_actions(build_vacation_steps(SEASON_COOLING))
        by_ent = {
            a["data"]["entity_id"]: a["data"]["value"]
            for a in actions if a["action"] == "number/set_value"
        }
        self.assertEqual(by_ent["number.aeco_1988_cold_tank_target_temperature"], "18")
        self.assertNotIn("number.aeco_1988_cold_tank_min_temperature", by_ent)
        self.assertNotIn("number.aeco_1988_cold_tank_max_temperature", by_ent)

    def test_cooling_leaves_reset_off_no_minmax(self):
        """Cooling holds a fixed target: reset off and no min/max writes."""
        for build in (build_home_steps, build_vacation_steps):
            actions = _all_actions(build(SEASON_COOLING))
            reset_off = [
                a for a in actions
                if a["action"] == "switch/turn_off"
                and a["data"].get("entity_id") == "switch.aeco_1988_cold_tank_outdoor_reset"
            ]
            self.assertEqual(len(reset_off), 1)
            minmax = [
                a for a in actions
                if a["action"] == "number/set_value"
                and a["data"].get("entity_id", "").endswith(("cold_tank_min_temperature", "cold_tank_max_temperature"))
            ]
            self.assertEqual(minmax, [])


class StartExecutionSeasonTests(TestCase):
    """start_execution should record and honour the detected season."""

    def setUp(self):
        if _execution_lock.locked():
            _execution_lock.release()
        _runs.clear()

    def tearDown(self):
        time.sleep(0.2)
        if _execution_lock.locked():
            _execution_lock.release()
        _runs.clear()

    @patch("vacation_mode.executor.call_ha_service")
    @patch("vacation_mode.executor.get_current_season", return_value=("cooling", 22.0))
    def test_cooling_season_stored_and_builds_cooling_steps(self, mock_season, mock_call):
        mock_call.return_value = (True, None)
        run_id, error = start_execution("vacation", dry_run=True)
        self.assertIsNone(error)
        self.assertEqual(_runs[run_id]["season"], "cooling")
        self.assertEqual(_runs[run_id]["season_avg"], 22.0)
        aliases = [s["alias"] for s in _runs[run_id]["steps"]]
        self.assertIn("Heat Pump Setup — Cooling", aliases)

    @patch("vacation_mode.executor.call_ha_service")
    @patch("vacation_mode.executor.get_current_season", return_value=("heating", 3.0))
    def test_heating_season_stored_and_builds_heating_steps(self, mock_season, mock_call):
        mock_call.return_value = (True, None)
        run_id, error = start_execution("home", dry_run=True)
        self.assertIsNone(error)
        self.assertEqual(_runs[run_id]["season"], "heating")
        aliases = [s["alias"] for s in _runs[run_id]["steps"]]
        self.assertIn("Heat Pump Setup — Heating", aliases)


# --------------------------------------------------------------------------
# bdl_modes (AppDaemon) client

from django.contrib.auth.models import User  # noqa: E402
from django.test import override_settings  # noqa: E402

from . import bdl_client  # noqa: E402

BM_URL = "http://appdaemon.test:5050/api/appdaemon/bdl_modes"
BM_STATUS = {"active": None, "history": [], "dry_run": True,
             "occupancy": "away", "season": "heating", "season_avg": 3.0,
             "leads_h": {"house": 24, "amenities": 6}}
BM_PREVIEW = {"season": "heating", "groups": [
    {"name": "house", "label": "Heat the house",
     "steps": [{"id": "thermostats_home", "alias": "Set Thermostats",
                "icon": "fas fa-fire"}]}]}


def _resp(code, payload):
    r = MagicMock()
    r.status_code = code
    r.json.return_value = payload
    return r


@override_settings(BDL_MODES_URL=BM_URL, BDL_MODES_API_KEY="secret",
                   BDL_MODES_PREHEAT=True)
class BdlClientTests(TestCase):
    @patch("vacation_mode.bdl_client.requests.post")
    def test_sends_key_and_drops_none_fields(self, post):
        post.return_value = _resp(200, BM_STATUS)
        data, err, code = bdl_client.call("home", arrival=None,
                                          skip_steps=["x"])
        self.assertEqual((data, err, code), (BM_STATUS, None, 200))
        args, kwargs = post.call_args
        self.assertEqual(args[0], BM_URL)
        self.assertEqual(kwargs["headers"]["X-API-Key"], "secret")
        self.assertEqual(kwargs["json"], {"cmd": "home", "skip_steps": ["x"]})

    @patch("vacation_mode.bdl_client.requests.post")
    def test_unreachable(self, post):
        post.side_effect = requests_lib.ConnectionError("refused")
        data, err, code = bdl_client.call("status")
        self.assertIsNone(data)
        self.assertEqual(code, 502)
        self.assertIn("unreachable", err)

    @patch("vacation_mode.bdl_client.requests.post")
    def test_error_passthrough(self, post):
        post.return_value = _resp(400, {"error": "arrival must be in the future"})
        _, err, code = bdl_client.call("preheat", arrival="2001-01-01T00:00")
        self.assertEqual((err, code), ("arrival must be in the future", 400))


@override_settings(BDL_MODES_URL=BM_URL, BDL_MODES_API_KEY="secret",
                   BDL_MODES_PREHEAT=True)
class BdlModesViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.client = Client()

    def login(self, staff=False):
        self.user.is_staff = staff
        self.user.save()
        self.client.force_login(self.user)

    def test_requires_login(self):
        r = self.client.get("/vacation_mode/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])
        r = self.client.post("/vacation_mode/api/modes/command/",
                             data=json.dumps({"cmd": "home"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 302)

    @patch("vacation_mode.views.bdl_client.call")
    def test_page_renders_status_and_previews(self, call):
        call.side_effect = lambda cmd, **kw: (
            (BM_STATUS if cmd == "status" else BM_PREVIEW), None, 200)
        self.login()
        r = self.client.get("/vacation_mode/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="bm-status"')
        self.assertContains(r, "thermostats_home")
        self.assertEqual(r.context["status"]["occupancy"], "away")

    @patch("vacation_mode.views.bdl_client.call")
    def test_page_shows_error_when_unreachable(self, call):
        call.return_value = (None, "Lodge controller unreachable: x", 502)
        self.login()
        r = self.client.get("/vacation_mode/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Lodge controller unreachable")

    @patch("vacation_mode.views.bdl_client.call")
    def test_command_allowlist(self, call):
        self.login()
        r = self.client.post("/vacation_mode/api/modes/command/",
                             data=json.dumps({"cmd": "preview"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        call.assert_not_called()

    @patch("vacation_mode.views.bdl_client.call")
    def test_command_forwards_fields(self, call):
        call.return_value = (BM_STATUS, None, 200)
        self.login()
        r = self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "preheat", "arrival": "2030-01-02T16:00", "request_id": "r1",
             "skip_steps": ["media_on"]}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        call.assert_called_once_with("preheat", arrival="2030-01-02T16:00",
                                     skip_steps=["media_on"], request_id="r1",
                                     dry_run=None)

    @patch("vacation_mode.views.bdl_client.call")
    def test_dry_run_only_for_staff(self, call):
        call.return_value = (BM_STATUS, None, 200)
        self.login(staff=False)
        self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "home", "dry_run": True}), content_type="application/json")
        self.assertIsNone(call.call_args.kwargs["dry_run"])
        self.login(staff=True)
        self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "home", "dry_run": True}), content_type="application/json")
        self.assertTrue(call.call_args.kwargs["dry_run"])

    @patch("vacation_mode.views.bdl_client.call")
    def test_bad_skip_steps(self, call):
        self.login()
        r = self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "home", "skip_steps": [1, 2]}), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        call.assert_not_called()

    @patch("vacation_mode.views.bdl_client.call")
    def test_controller_error_status_passthrough(self, call):
        call.return_value = (None, "no active preheat to update", 400)
        self.login()
        r = self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "update_arrival", "arrival": "2030-01-01T10:00"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "no active preheat to update")

    @override_settings(BDL_MODES_PREHEAT=False)
    @patch("vacation_mode.views.bdl_client.call")
    def test_preheat_flag(self, call):
        self.login()
        r = self.client.post("/vacation_mode/api/modes/command/", data=json.dumps(
            {"cmd": "preheat", "arrival": "2030-01-01T10:00"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 400)
        call.assert_not_called()

    @patch("vacation_mode.views.bdl_client.call")
    def test_status_proxy(self, call):
        call.return_value = (BM_STATUS, None, 200)
        self.login()
        r = self.client.get("/vacation_mode/api/modes/status/")
        self.assertEqual(r.json()["occupancy"], "away")


@override_settings(BDL_MODES_URL="")
class BdlModesDisabledTests(TestCase):
    @patch("vacation_mode.views.get_away_mode_state", return_value=False)
    @patch("vacation_mode.views.get_active_run", return_value=None)
    @patch("vacation_mode.views.get_current_season", return_value=("heating", 5.0))
    @patch("vacation_mode.views.bdl_client.call")
    def test_legacy_page_without_url(self, call, *_):
        client = Client()
        client.force_login(User.objects.create_user("u", password="p"))
        r = client.get("/vacation_mode/")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "vacation_mode/vacation_mode.html")
        call.assert_not_called()


@override_settings(BDL_MODES_URL="")
class LegacyViewsRequireLoginTests(TestCase):
    """Legacy vacation-mode page and API must not be reachable anonymously."""

    def test_page_redirects_to_login(self):
        r = self.client.get("/vacation_mode/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])

    @patch("vacation_mode.views.start_execution")
    def test_execute_rejected(self, mock_start):
        r = self.client.post(
            "/vacation_mode/api/execute/",
            data=json.dumps({"mode": "vacation"}),
            content_type="application/json",
        )
        self.assertNotEqual(r.status_code, 200)
        self.assertIn("login", r["Location"])
        mock_start.assert_not_called()

    @patch("vacation_mode.views.get_active_run")
    @patch("vacation_mode.views.get_away_mode_state")
    def test_state_rejected(self, mock_away, mock_active):
        r = self.client.get("/vacation_mode/api/state/")
        self.assertNotEqual(r.status_code, 200)
        self.assertIn("login", r["Location"])
        mock_away.assert_not_called()

    @patch("vacation_mode.views.get_run_status")
    def test_status_rejected(self, mock_status):
        r = self.client.get("/vacation_mode/api/status/abc123/")
        self.assertNotEqual(r.status_code, 200)
        self.assertIn("login", r["Location"])
        mock_status.assert_not_called()
