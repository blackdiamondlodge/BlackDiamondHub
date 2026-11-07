from hub.plugins import PluginSpec, Tile

spec = PluginSpec(
    id="snow_report",
    app="snow_report",
    urls="snow_report.urls",
    tiles=(
        Tile(
            title="Snow Report",
            url_name="snow_report",
            icon="snow_report/hub/icon.svg",
            section="mountain",
            subtitle="Fresh snow & conditions",
            order=10,
        ),
    ),
)
