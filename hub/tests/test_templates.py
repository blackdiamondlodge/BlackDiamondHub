"""App templates are namespaced under <app>/templates/<app_label>/."""
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase

_REFERENCE = re.compile(r"""{%\s*(?:extends|include)\s+["']([^"']+)["']""")
CORE_TEMPLATES = {"base.html", "hub_settings/_layout.html"}


def _plugin_apps():
    for spec in settings.HUB_PLUGINS:
        yield apps.get_app_config(spec.app.split(".")[-1])


class TemplateNamespacingTests(SimpleTestCase):
    def test_app_templates_are_namespaced_and_load(self):
        for config in _plugin_apps():
            root = Path(config.path) / "templates"
            if not root.is_dir():
                continue
            for path in root.rglob("*.html"):
                name = path.relative_to(root).as_posix()
                with self.subTest(template=name):
                    self.assertTrue(
                        name.startswith(f"{config.label}/"),
                        f"{name} must live under templates/{config.label}/",
                    )
                    get_template(name)
                    for ref in _REFERENCE.findall(path.read_text(encoding="utf-8")):
                        if ref not in CORE_TEMPLATES:
                            self.assertTrue(
                                ref.startswith(f"{config.label}/"),
                                f"{name} references un-namespaced {ref}",
                            )
                        get_template(ref)
