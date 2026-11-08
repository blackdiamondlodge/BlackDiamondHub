"""
Test-only settings override: run the Django test suite against an in-memory
SQLite database so tests don't require a live PostgreSQL server.

Usage:
    python manage.py test hub --settings=BlackDiamondHub.settings_test
"""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")

from .settings import *  # noqa: F401,F403,E402

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
