"""Settings navigation for app-drawn settings pages (``PluginSpec.settings_pages``).

An app's page can extend ``hub_settings/_layout.html`` and only pass
``active`` (its app id); the section lists come from here. They're callables
so other pages never pay for building them.
"""


def settings_nav(request):
    from . import views

    return {"lodge_sections": views._lodge_sections, "app_sections": views._app_sections}
