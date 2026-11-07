from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="device_control",
    app="device_control",
    urls="device_control.urls",
    tiles=(
        Tile(
            title="Fireplaces & Devices",
            url_name="device_control",
            icon="device_control/hub/icon.svg",
            section="lodge",
            subtitle="Fireplaces, blinds & more",
            order=30,
        ),
    ),
)
