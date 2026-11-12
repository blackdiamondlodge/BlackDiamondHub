"""Acceptance smoke test for installed hub apps.

Used by the hub's own tests and by the reusable app CI in bdh-sdk, after an
app's wheel has been installed next to the hub:

    python manage.py hub_smoke --app wifi

For each selected plugin it checks that every hook path imports, every tile
icon is found by the static finders, and every tile page renders (status
below 500) for a signed-in superuser. Pages run against a throwaway test
database, so it is safe to point at any settings module.
"""
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import reverse

from hub.loader import DOTTED_FIELDS


def _resolve(path):
    module, _, attr = path.rpartition(".")
    return getattr(import_module(module), attr)


class Command(BaseCommand):
    help = "Check that installed hub apps load, resolve and render."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app", action="append", dest="apps", default=[],
            help="Plugin id to check (repeatable). Default: all plugins.",
        )

    def handle(self, *args, apps=(), **options):
        specs = {spec.id: spec for spec in settings.HUB_PLUGINS}
        missing = [a for a in apps if a not in specs]
        if missing:
            raise CommandError(
                "plugin(s) not installed: %s (installed: %s)"
                % (", ".join(missing), ", ".join(sorted(specs)))
            )
        selected = [specs[a] for a in apps] if apps else list(specs.values())

        problems = []
        for spec in selected:
            hooks = [(name, getattr(spec, name)) for name in DOTTED_FIELDS]
            hooks += [(f"provides[{cap}]", path) for cap, path in (spec.provides or {}).items()]
            for name, path in hooks:
                if path:
                    try:
                        _resolve(path)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{spec.id}: {name} {path!r}: {exc!r}")
            for tile in spec.tiles:
                if not finders.find(tile.icon):
                    problems.append(f"{spec.id}: icon {tile.icon!r} not found")

        problems += self._render(selected)
        for spec in selected:
            self.stdout.write(f"checked {spec.id} ({len(spec.tiles)} tile(s))")
        if problems:
            raise CommandError("smoke test failed:\n  " + "\n  ".join(problems))
        self.stdout.write(self.style.SUCCESS("hub smoke OK"))

    def _render(self, specs):
        problems = []
        setup_test_environment()
        old_name = connection.creation.create_test_db(verbosity=0, autoclobber=True)
        try:
            user = get_user_model().objects.create_superuser(
                "hub-smoke", "smoke@example.invalid", "unused-password"
            )
            client = Client(raise_request_exception=False)
            client.force_login(user)
            for spec in specs:
                for tile in spec.tiles:
                    try:
                        url = reverse(tile.url_name)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{spec.id}: url {tile.url_name!r}: {exc}")
                        continue
                    status = client.get(url).status_code
                    self.stdout.write(f"  {spec.id}: GET {url} -> {status}")
                    if status >= 500:
                        problems.append(f"{spec.id}: GET {url} returned {status}")
        finally:
            connection.creation.destroy_test_db(old_name, verbosity=0)
            teardown_test_environment()
        return problems
