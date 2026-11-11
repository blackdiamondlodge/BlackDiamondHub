from hub.plugins import PluginSpec

from .options import SETTINGS

spec = PluginSpec(id="display", app="display", urls="display.urls", settings=SETTINGS)
