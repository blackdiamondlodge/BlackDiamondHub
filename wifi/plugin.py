from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="wifi",
    app="wifi",
    urls="wifi.urls",
    tiles=(
        Tile(
            title="WiFi",
            url_name="wifi_qr",
            icon="wifi/hub/icon.svg",
            section="more",
            subtitle="Scan to connect",
            order=10,
        ),
    ),
)
