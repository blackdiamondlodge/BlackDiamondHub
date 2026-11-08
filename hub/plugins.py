"""Plugin contract for Black Diamond Hub apps.

Every app (built-in or installed from its own repo) describes itself with a
single ``PluginSpec``. The hub reads these specs to add the app to
INSTALLED_APPS, mount its URLs and put its tiles on the homepage.

This module is the public surface that plugin repos import, so it must stay
free of Django model/settings imports: specs are loaded while settings are
still being built.
"""
from dataclasses import dataclass, field

API_VERSION = 1

# Homepage modes. "guest" is used while a stay is active, "dashboard" when the
# lodge is between stays, "owner" when someone is signed in.
GUEST = "guest"
DASHBOARD = "dashboard"
OWNER = "owner"
ALL_MODES = frozenset({GUEST, DASHBOARD, OWNER})
OWNER_ONLY = frozenset({OWNER})

# Homepage sections, in display order.
SECTIONS = {
    "mountain": "On the mountain",
    "lodge": "In the lodge",
    "more": "More",
}


@dataclass(frozen=True)
class Tile:
    """A homepage tile that links to one of the app's pages.

    ``modes`` only controls where the tile is shown. Views behind an
    owner-only tile must still enforce sign-in themselves.
    """

    title: str
    url_name: str
    icon: str  # static path, e.g. "wifi/hub/icon.svg"
    section: str
    subtitle: str = ""
    order: int = 100
    modes: frozenset = ALL_MODES


# Status levels. "on" highlights something that is running (lights on, lifts
# open), "warn" flags a problem the user may want to look at.
INFO = "info"
ON = "on"
WARN = "warn"
STATUS_LEVELS = frozenset({INFO, ON, WARN})


@dataclass(frozen=True)
class Status:
    """A one-line summary shown on the app's homepage tile."""

    text: str
    level: str = INFO


@dataclass(frozen=True)
class Shortcut:
    """A one-tap action shown in the homepage quick actions row.

    Shortcuts are owner-only unless the app lists other modes explicitly,
    because guest and dashboard modes don't require sign-in.
    """

    id: str
    title: str
    icon: str  # Font Awesome classes, e.g. "fa-solid fa-film"
    order: int = 100
    modes: frozenset = OWNER_ONLY


@dataclass(frozen=True)
class PluginSpec:
    """Describes one hub app.

    ``id`` is permanent: it names the URL prefix by default and will
    namespace the app's settings and data in future.

    The hooks are dotted paths so this module stays importable before
    Django is set up. They are resolved on first use:

    - ``status``: ``() -> Status | None``. Called in a worker thread with a
      timeout; return None when there is nothing worth showing.
    - ``shortcuts``: ``() -> iterable of Shortcut``.
    - ``run_shortcut``: ``(shortcut_id) -> str | None``. Runs a shortcut the
      hub has already checked is offered in the caller's mode. Raise to
      report failure; the optional return value is shown to the user.
    - ``websocket_routes``: a list of Channels URL patterns (e.g.
      ``"myapp.routing.websocket_urlpatterns"``). Imported by the ASGI
      application after Django is set up and mounted under the shared
      websocket router.
    """

    id: str
    app: str  # Django app module or AppConfig path for INSTALLED_APPS
    urls: str | None = None  # URLconf module, mounted at url_prefix
    url_prefix: str | None = None  # defaults to "<id>/"
    tiles: tuple[Tile, ...] = field(default_factory=tuple)
    status: str | None = None
    shortcuts: str | None = None
    run_shortcut: str | None = None
    websocket_routes: str | None = None
    api_version: int = API_VERSION

    @property
    def prefix(self) -> str:
        return self.url_prefix if self.url_prefix is not None else f"{self.id}/"
