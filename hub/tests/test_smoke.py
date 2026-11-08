import subprocess
import sys
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class HubSmokeCommandTests(SimpleTestCase):
    def test_unknown_app_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "not installed: nope"):
            call_command("hub_smoke", apps=["nope"])

    def test_smoke_passes_for_an_app(self):
        # Runs in its own process: the command creates its own test database.
        result = subprocess.run(
            [sys.executable, "manage.py", "hub_smoke", "--app", "lift_status",
             "--settings=BlackDiamondHub.settings_test"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("lift_status: GET /lift_status/ -> 200", result.stdout)
        self.assertIn("hub smoke OK", result.stdout)
