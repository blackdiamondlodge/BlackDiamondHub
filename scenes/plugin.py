from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="scenes",
    app="scenes",
    urls="scenes.urls",
    tiles=(
        Tile(
            title="Lights & Scenes",
            url_name="scenes",
            icon="scenes/hub/icon.svg",
            section="lodge",
            subtitle="Set the mood",
            order=10,
        ),
    ),
)
