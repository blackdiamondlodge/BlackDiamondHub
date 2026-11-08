"""Every <app>/plugin.py must be importable without side effects.

Specs are loaded while settings are still being built (and, once apps live
in their own repos, by entry-point discovery), so importing one must not set
up Django, touch models, call Home Assistant or start threads.
"""
import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

PROBE = r"""
import json, sys, threading

module, app = sys.argv[1], sys.argv[2]
before_threads = {t.ident for t in threading.enumerate()}
before_modules = set(sys.modules)

import importlib
spec = getattr(importlib.import_module(module), "spec")

new_modules = set(sys.modules) - before_modules
forbidden = sorted(
    m for m in new_modules
    if m == "requests" or m.startswith("requests.")
    or m in {app + ".models", app + ".views", app + ".homepage"}
    or m.endswith(".models")
)
apps_ready = False
if "django.apps" in sys.modules:
    apps_ready = sys.modules["django.apps"].apps.ready
settings_configured = False
if "django.conf" in sys.modules:
    settings_configured = sys.modules["django.conf"].settings.configured
print(json.dumps({
    "spec_type": type(spec).__name__,
    "forbidden": forbidden,
    "new_threads": [t.name for t in threading.enumerate() if t.ident not in before_threads],
    "apps_ready": apps_ready,
    "settings_configured": settings_configured,
}))
"""


def _plugin_modules():
    for spec in settings.HUB_PLUGINS:
        module = f"{spec.app.split('.')[0]}.plugin"
        if find_spec(module) is not None:
            yield module, spec.app.split(".")[0]


class PluginEntrypointTests(SimpleTestCase):
    def test_builtin_plugins_found(self):
        self.assertGreaterEqual(len(list(_plugin_modules())), 12)

    def test_plugin_modules_import_without_side_effects(self):
        env = {k: v for k, v in os.environ.items()
               if k != "DJANGO_SETTINGS_MODULE"}
        for module, app in _plugin_modules():
            with self.subTest(module=module):
                proc = subprocess.run(
                    [sys.executable, "-c", PROBE, module, app],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                result = json.loads(proc.stdout.strip().splitlines()[-1])
                self.assertEqual(result["spec_type"], "PluginSpec")
                self.assertEqual(result["forbidden"], [])
                self.assertEqual(result["new_threads"], [])
                self.assertFalse(result["apps_ready"])
                self.assertFalse(result["settings_configured"])
