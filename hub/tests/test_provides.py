import threading
import time
from datetime import datetime, timezone

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from bdh_sdk.provides import BACKGROUNDS, SEASON, STATS, WINTER, Background, SeasonHint, Stat
from hub import provides
from hub.loader import PluginError, validate
from hub.plugins import PluginSpec

STATE = {}
P = "hub.tests.test_provides."


def snow_stats():
    if STATE.get("fail"):
        raise RuntimeError("site down")
    return [
        Stat("snow_24h", "24h snow", value=STATE.get("snow", "5 cm"), order=1),
        Stat("sunrise", "Sunrise", time=datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)),
        Stat("secret", "Undeclared", value="x"),
        Stat("snow_24h", "Duplicate", value="ignored"),
    ]


def bad_stats():
    return ["not a stat"]


def slow_stats():
    STATE["release"].wait(5)
    return [Stat("price", "Price", value="1")]


def cams():
    return (Background("sunburst", "Sunburst", "http://cam/sunburst.jpg", refresh_seconds=30),
            Background("empty", "No image", ""))


def winter():
    return SeasonHint(WINTER, "Lifts are open") if STATE.get("open") else None


def _stats_spec(id="snow_report", path=P + "snow_stats", **kw):
    return PluginSpec(id=id, app=id, provides={STATS: path},
                      stat_keys=(("snow_24h", "24h snow"), ("sunrise", "Sunrise")), **kw)


# A headless app: provides data, no tiles or URLs.
HEADLESS = PluginSpec(id="ticker", app="ticker", provides={STATS: P + "slow_stats"},
                      stat_keys=(("price", "Price"),))


class ProvidesTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        STATE.clear()
        self.addCleanup(cache.clear)

    def test_stats_are_qualified_checked_and_serialised(self):
        with override_settings(HUB_PLUGINS=(_stats_spec(),)):
            data = provides.stats()
        self.assertEqual(data, {
            "snow_report.snow_24h": {"label": "24h snow", "order": 1, "value": "5 cm"},
            "snow_report.sunrise": {"label": "Sunrise", "order": 100, "time": "2026-11-12T15:30:00Z"},
        })

    def test_catalogue_comes_from_declared_keys_without_calling(self):
        STATE["fail"] = True
        with override_settings(HUB_PLUGINS=(_stats_spec(), HEADLESS)):
            self.assertEqual(provides.stat_catalogue(), [
                ("snow_report.snow_24h", "24h snow", "Snow Report"),
                ("snow_report.sunrise", "Sunrise", "Snow Report"),
                ("ticker.price", "Price", "Ticker"),
            ])
            self.assertEqual(provides.stat_owners(), {"snow_report", "ticker"})

    def test_malformed_output_is_left_out(self):
        plugins = (_stats_spec(), _stats_spec(id="broken", path=P + "bad_stats"))
        with override_settings(HUB_PLUGINS=plugins):
            data = provides.stats()
        self.assertIn("snow_report.snow_24h", data)
        self.assertFalse(any(key.startswith("broken.") for key in data))

    def test_failure_serves_last_good_value(self):
        with override_settings(HUB_PLUGINS=(_stats_spec(),)):
            provides.stats()
            cache.delete("hub:provide:stats:snow_report")
            STATE.update(fail=True)
            self.assertEqual(provides.stats()["snow_report.snow_24h"]["value"], "5 cm")

    def test_slow_provider_times_out_without_blocking(self):
        STATE["release"] = threading.Event()
        try:
            with override_settings(HUB_PLUGINS=(_stats_spec(), HEADLESS)):
                started = time.monotonic()
                data = provides.stats(timeout=0.2)
            self.assertLess(time.monotonic() - started, 2)
            self.assertIn("snow_report.snow_24h", data)
            self.assertNotIn("ticker.price", data)
        finally:
            STATE["release"].set()

    def test_only_requested_providers_are_called(self):
        STATE["release"] = threading.Event()
        STATE["release"].set()
        with override_settings(HUB_PLUGINS=(_stats_spec(), HEADLESS)):
            self.assertEqual(set(provides.stats(plugin_ids={"ticker"})), {"ticker.price"})

    def test_removed_provider_is_gone(self):
        with override_settings(HUB_PLUGINS=(_stats_spec(),)):
            self.assertTrue(provides.stats())
        with override_settings(HUB_PLUGINS=()):
            self.assertEqual(provides.stats(), {})
            self.assertEqual(provides.stat_catalogue(), [])

    def test_backgrounds_and_season_hints(self):
        plugins = (PluginSpec(id="cams", app="cams", provides={BACKGROUNDS: P + "cams"}),
                   PluginSpec(id="lifts", app="lifts", provides={SEASON: P + "winter"}))
        with override_settings(HUB_PLUGINS=plugins):
            self.assertEqual(provides.backgrounds(), [{
                "id": "cams.sunburst", "label": "Sunburst", "url": "http://cam/sunburst.jpg",
                "refresh_seconds": 30, "live": True, "app": "Cams",
            }])
            self.assertEqual(provides.season_hints(), [])
            cache.clear()
            STATE["open"] = True
            self.assertEqual(provides.season_hints(),
                             [{"app": "Lifts", "season": "winter", "reason": "Lifts are open"}])

    def test_headless_app_is_valid_and_provides(self):
        STATE["release"] = threading.Event()
        STATE["release"].set()
        self.assertEqual(validate([HEADLESS]), [HEADLESS])
        with override_settings(HUB_PLUGINS=(HEADLESS,)):
            self.assertEqual(provides.stats()["ticker.price"]["value"], "1")

    def test_unknown_capability_is_ignored(self):
        spec = PluginSpec(id="future", app="future", provides={"weather_alerts": P + "cams"})
        with override_settings(HUB_PLUGINS=(spec,)):
            validate([spec])
            self.assertEqual(provides.providers(BACKGROUNDS), [])


class ProvidesValidationTests(SimpleTestCase):
    def test_rejects_provider_that_is_not_a_dotted_path(self):
        with self.assertRaisesMessage(PluginError, "provides 'stats' must be a dotted"):
            validate([PluginSpec(id="a", app="a", provides={STATS: "stats"})])

    def test_rejects_card_that_is_not_a_dotted_path(self):
        with self.assertRaisesMessage(PluginError, "card must be a dotted"):
            validate([PluginSpec(id="a", app="a", card="card")])
