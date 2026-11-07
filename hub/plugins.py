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


@dataclass(frozen=True)
class PluginSpec:
    """Describes one hub app.

    ``id`` is permanent: it names the URL prefix by default and will
    namespace the app's settings and data in future.
    """

    id: str
    app: str  # Django app module or AppConfig path for INSTALLED_APPS
    urls: str | None = None  # URLconf module, mounted at url_prefix
    url_prefix: str | None = None  # defaults to "<id>/"
    tiles: tuple[Tile, ...] = field(default_factory=tuple)
    api_version: int = API_VERSION

    @property
    def prefix(self) -> str:
        return self.url_prefix if self.url_prefix is not None else f"{self.id}/"
