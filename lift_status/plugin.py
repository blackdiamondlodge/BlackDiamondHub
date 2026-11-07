from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="lift_status",
    app="lift_status",
    urls="lift_status.urls",
    tiles=(
        Tile(
            title="Lift Status",
            url_name="lift_status",
            icon="lift_status/hub/icon.svg",
            section="mountain",
            subtitle="Which lifts are running",
            order=20,
        ),
    ),
)
