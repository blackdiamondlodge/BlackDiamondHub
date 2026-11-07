from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="cameras",
    app="cameras",
    urls="cameras.urls",
    tiles=(
        Tile(
            title="Cameras",
            url_name="cameras",
            icon="cameras/hub/icon.svg",
            section="more",
            subtitle="Outdoor cameras",
            order=20,
        ),
    ),
)
