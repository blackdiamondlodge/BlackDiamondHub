from hub.plugins import OWNER_ONLY, PluginSpec, Tile

spec = PluginSpec(
    id="vacation_mode",
    app="vacation_mode",
    urls="vacation_mode.urls",
    tiles=(
        Tile(
            title="Vacation Mode",
            url_name="vacation_mode",
            icon="vacation_mode/hub/icon.svg",
            section="more",
            subtitle="Away & arrival",
            order=30,
            modes=OWNER_ONLY,
        ),
    ),
)
