import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from hub.context_processors import nav_title, stay_key
from hub.loader import PluginError, load_plugins, validate
from hub.modes import tiles_for_mode
from hub.plugins import (
    ALL_MODES, DASHBOARD, GUEST, ON, OWNER, OWNER_ONLY, WARN, Card, PluginSpec, Reading, Shortcut,
    Status, StatusRow, Stay, Tile, Action,
)
from hub.status import _status_value, current_stay, home_data
from hub_settings import store as hub_store
from hub_settings.models import AppSetting


def _tile(**kw):
    defaults = dict(title="T", url_name="wifi_qr", icon="wifi/hub/icon.svg", section="more")
    defaults.update(kw)
    return Tile(**defaults)


class LoaderValidationTests(SimpleTestCase):
    def test_loader_rejects_hook_that_is_not_a_dotted_path(self):
        with self.assertRaisesMessage(PluginError, "websocket_routes must be a dotted"):
            validate([PluginSpec(id="a", app="a", websocket_routes="routing")])
        with self.assertRaisesMessage(PluginError, "status must be a dotted"):
            validate([PluginSpec(id="a", app="a", status=print)])

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesMessage(PluginError, "duplicate plugin id"):
            validate([PluginSpec(id="a", app="a"), PluginSpec(id="a", app="b")])

    def test_rejects_duplicate_url_prefixes(self):
        with self.assertRaisesMessage(PluginError, "duplicate URL prefix"):
            validate([
                PluginSpec(id="a", app="a", urls="a.urls", url_prefix="x/"),
                PluginSpec(id="b", app="b", urls="b.urls", url_prefix="x/"),
            ])

    def test_rejects_unknown_section(self):
        with self.assertRaisesMessage(PluginError, "unknown section"):
            validate([PluginSpec(id="a", app="a", tiles=(_tile(section="garage"),))])

    def test_rejects_other_api_version(self):
        with self.assertRaisesMessage(PluginError, "hub API"):
            validate([PluginSpec(id="a", app="a", api_version=99)])

    def test_loads_entry_point_plugins(self):
        external = PluginSpec(id="external", app="external", urls="external.urls")
        ep = MagicMock()
        ep.load.return_value = external
        with patch("hub.loader.entry_points", return_value=[ep]) as eps:
            specs = load_plugins(["radiant.plugin.spec"])
        eps.assert_called_once_with(group="blackdiamondhub.plugins")
        self.assertEqual([s.id for s in specs], ["radiant", "external"])


class TileModeTests(TestCase):
    plugins = (
        PluginSpec(id="wifi", app="wifi", tiles=(_tile(title="WiFi"),)),
        PluginSpec(id="vacation_mode", app="vacation_mode", tiles=(
            _tile(title="Vacation", url_name="vacation_mode", modes=OWNER_ONLY),
        )),
        PluginSpec(id="ghost", app="ghost", tiles=(_tile(title="Ghost", url_name="no_such_url"),)),
    )

    def setUp(self):
        hub_store.clear()
        self.addCleanup(hub_store.clear)

    def sections(self, mode, plugins=None):
        with override_settings(HUB_PLUGINS=plugins or self.plugins):
            return {key: items for key, _, items in tiles_for_mode(mode)}

    def titles(self, mode):
        return [t["title"] for items in self.sections(mode).values() for t in items if t["kind"] == "app"]

    def save_layout(self, layout):
        AppSetting.objects.update_or_create(app_id="hub", key="home_layout", defaults={"value": layout})

    def test_owner_only_tiles_are_hidden_from_other_modes(self):
        self.assertEqual(self.titles(GUEST), ["WiFi"])
        self.assertEqual(self.titles(DASHBOARD), ["WiFi"])
        self.assertEqual(self.titles(OWNER), ["Vacation", "WiFi"])

    def test_tile_with_unknown_url_is_skipped(self):
        self.assertNotIn("Ghost", self.titles(OWNER))

    def test_default_layout_leads_with_one_large_tile(self):
        def sizes(n):
            tiles = tuple(_tile(title=f"T{i}", order=i) for i in range(n))
            items = self.sections(OWNER, (PluginSpec(id="a", app="a", tiles=tiles),))["more"]
            return [t["size"] for t in items]

        self.assertEqual(sizes(1), ["l"])
        self.assertEqual(sizes(2), ["l", "m"])
        self.assertEqual(sizes(3), ["l", "m", "m"])

    def test_weather_is_built_in_and_a_lone_lodge_card_has_no_section(self):
        sections = self.sections(OWNER)
        self.assertEqual([t["kind"] for t in sections["mountain"]], ["weather"])
        self.assertNotIn("lodge", sections)

    def test_saved_layout_orders_and_sizes_tiles(self):
        self.save_layout({"more": [
            {"id": "wifi:wifi_qr", "size": "s"},
            {"id": "vacation_mode:vacation_mode", "size": "huge"},
            {"id": "gone:app", "size": "l"},
        ]})
        items = self.sections(OWNER)["more"]
        self.assertEqual([(t["title"], t["size"]) for t in items], [("WiFi", "s"), ("Vacation", "m")])

    def test_tiles_missing_from_saved_layout_follow_it(self):
        self.save_layout({"more": [{"id": "wifi:wifi_qr", "size": "m"}]})
        self.assertEqual(self.titles(OWNER), ["WiFi", "Vacation"])

    def test_malformed_saved_layout_is_ignored(self):
        self.save_layout(["not", "a", "dict"])
        self.assertEqual(self.titles(OWNER), ["Vacation", "WiFi"])

    def groups(self, mode=OWNER, **kw):
        with override_settings(HUB_PLUGINS=self.plugins):
            return [(key, title, [t["id"] for t in items]) for key, title, items in tiles_for_mode(mode, **kw)]

    def test_groups_can_be_renamed_reordered_and_added(self):
        self.save_layout({"groups": [
            {"key": "g-fav", "title": "Favourites", "tiles": [{"id": "wifi:wifi_qr", "size": "s"}]},
            {"key": "more", "title": "Everything else", "tiles": []},
            {"key": "mountain", "title": "Outside", "tiles": [{"id": "hub:weather", "size": "m"}]},
        ]})
        self.assertEqual(self.groups(), [
            ("g-fav", "Favourites", ["wifi:wifi_qr"]),
            ("more", "Everything else", ["vacation_mode:vacation_mode"]),
            ("mountain", "Outside", ["hub:weather", "hub:lodge"]),
        ])

    def test_tile_moves_between_groups(self):
        self.save_layout({"groups": [
            {"key": "mountain", "title": "Out", "tiles": []},
            {"key": "lodge", "title": "In", "tiles": [{"id": "wifi:wifi_qr", "size": "m"}]},
            {"key": "more", "title": "More", "tiles": [{"id": "hub:weather", "size": "s"}]},
        ]})
        groups = self.groups()
        self.assertEqual(groups[0][0], "lodge")
        self.assertEqual(groups[0][2], ["wifi:wifi_qr", "hub:lodge"])
        self.assertIn("hub:weather", groups[1][2])

    def test_new_tile_lands_in_last_group_when_its_section_was_removed(self):
        self.save_layout({"groups": [
            {"key": "mountain", "title": "Out", "tiles": []},
            {"key": "g-x", "title": "Mine", "tiles": [{"id": "wifi:wifi_qr", "size": "s"}]},
        ]})
        last = self.groups()[-1]
        self.assertEqual(last[0], "g-x")
        self.assertEqual(last[2][0], "wifi:wifi_qr")
        self.assertEqual(set(last[2]), {"wifi:wifi_qr", "vacation_mode:vacation_mode", "hub:lodge"})

    def test_empty_groups_only_listed_when_asked(self):
        self.save_layout({"groups": [
            {"key": "g-empty", "title": "Empty", "tiles": []},
            {"key": "more", "title": "More", "tiles": []},
        ]})
        self.assertNotIn("g-empty", [g[0] for g in self.groups()])
        self.assertEqual(self.groups(include_empty=True)[0], ("g-empty", "Empty", []))

    def test_bad_saved_groups_fall_back(self):
        self.save_layout({"groups": [{"key": "BAD KEY", "title": "x", "tiles": []}, "junk"]})
        self.assertEqual([g[0] for g in self.groups(include_empty=True)], ["mountain", "lodge", "more"])


class NavTitleTests(SimpleTestCase):
    plugins = (
        PluginSpec(id="wifi", app="wifi", urls="wifi.urls", tiles=(_tile(title="WiFi"),)),
        PluginSpec(id="lodge", app="lodge", urls="lodge.urls", url_prefix="wifi/lodge/",
                   tiles=(_tile(title="Lodge", url_name="no_such_url"),)),
    )

    def title(self, path):
        with override_settings(HUB_PLUGINS=self.plugins):
            return nav_title(RequestFactory().get(path))["hub_nav_title"]

    def test_title_comes_from_the_app_that_owns_the_path(self):
        self.assertEqual(self.title("/wifi/"), "WiFi")
        self.assertEqual(self.title("/wifi/qr/extra/"), "WiFi")

    def test_longest_matching_prefix_wins(self):
        self.assertEqual(self.title("/wifi/lodge/"), "Lodge")

    def test_pages_outside_any_app_have_no_title(self):
        self.assertEqual(self.title("/"), "")
        self.assertEqual(self.title("/feedback/"), "")


class StayKeyTests(SimpleTestCase):
    def key(self, stay=None, error=None):
        with patch("hub.status.current_stay", return_value=stay, side_effect=error):
            return stay_key(RequestFactory().get("/"))["hub_stay_key"]()

    def stay(self, guest="The Smiths", day=4):
        return {"guest": guest, "arrival": datetime(2027, 1, day, 23, tzinfo=timezone.utc),
                "checkout": None, "owner": False}

    def test_no_stay_or_failed_lookup_gives_empty_key(self):
        self.assertEqual(self.key(None), "")
        self.assertEqual(self.key(error=RuntimeError("HA down")), "")

    def test_key_is_stable_per_stay_and_differs_between_stays(self):
        a = self.key(self.stay())
        self.assertEqual(a, self.key(self.stay()))
        self.assertNotIn("Smiths", a)
        self.assertNotEqual(a, self.key(self.stay(guest="The Joneses")))
        self.assertNotEqual(a, self.key(self.stay(day=11)))


class HomepageRegistryTests(TestCase):
    def setUp(self):
        cache.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        mock_get = patcher.start()
        self.addCleanup(patcher.stop)
        mock_get.return_value = MagicMock(status_code=200, content=b"")

    def test_homepage_renders_tiles_from_installed_plugins(self):
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], DASHBOARD)
        for href, icon in [
            ("/snow_report/", "snow_report/hub/icon.svg"),
            ("/radiant/", "radiant/hub/icon.svg"),
            ("/lift_status/", "lift_status/hub/icon.svg"),
        ]:
            self.assertContains(response, f'href="{href}"')
            self.assertContains(response, icon)

    def test_home_button_shows_only_away_from_the_homepage(self):
        self.assertNotContains(self.client.get("/"), 'id="home-button"')
        response = self.client.get("/wifi/")
        self.assertContains(response, 'id="home-button"')
        self.assertContains(response, '<div class="navhub-title">WiFi</div>', html=False)

    def test_navbar_flags_drive_the_phone_layout(self):
        # base.html's phone CSS keys off these: is-home keeps the monogram and inline extras,
        # is-owner moves Feedback into the avatar menu ("Send feedback").
        home = self.client.get("/").content.decode()
        self.assertRegex(home, r'<nav class="navbar[^"]* is-home')
        self.assertNotRegex(home, r'<nav class="navbar[^"]* is-owner')
        self.assertNotIn('class="hub-menu-fb"', home)
        self.client.force_login(User.objects.create_user("owner"))
        app = self.client.get("/wifi/").content.decode()
        self.assertRegex(app, r'<nav class="navbar[^"]* is-owner')
        self.assertNotRegex(app, r'<nav class="navbar[^"]* is-home')
        self.assertIn('class="hub-menu-fb"', app)

    def test_signed_in_user_gets_owner_mode(self):
        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertContains(response, "mode-owner")


class HealthCheckTests(TestCase):
    def test_healthz_ok_for_any_host(self):
        # The container probe uses 127.0.0.1, which is not in ALLOWED_HOSTS.
        response = self.client.get("/healthz", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_healthz_reports_database_failure(self):
        with patch("hub.health.connection.cursor", side_effect=Exception("db down")):
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")


class WebSocketOriginTests(SimpleTestCase):
    async def test_rejects_websocket_from_foreign_origin(self):
        from channels.testing import WebsocketCommunicator

        from BlackDiamondHub.asgi import application

        communicator = WebsocketCommunicator(
            application, "/ws/sonos_updates/", headers=[(b"origin", b"http://evil.example")]
        )
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

# ── Status lines and shortcuts ──────────────────────────────────────────

HOOK_STATE = {}


def ok_status():
    return Status("3 lights on", ON)


def failing_status():
    if HOOK_STATE.get("fail"):
        raise RuntimeError("boom")
    return Status("fine")


def slow_status():
    HOOK_STATE["release"].wait(5)
    return Status("late")


def gated_status():
    gate = HOOK_STATE.get("gate")
    if gate:
        gate.wait(5)
    if HOOK_STATE.get("gate_fails"):
        raise RuntimeError("HA down")
    return Status(HOOK_STATE.get("text", "first"))


def mode_status(mode):
    return Status(f"{mode} view")


def demo_shortcuts():
    return [
        Shortcut(id="movie", title="Movie", icon="fa-solid fa-film", modes=ALL_MODES),
        Shortcut(id="lock_up", title="Lock up", icon="fa-solid fa-lock"),
    ]


def demo_run(shortcut_id):
    HOOK_STATE.setdefault("ran", []).append(shortcut_id)
    if HOOK_STATE.get("run_fails"):
        raise RuntimeError("HA down")
    return "Enjoy the show"


def _spec(id, **kw):
    return PluginSpec(id=id, app=id, tiles=(_tile(title=id),), **kw)


STATUS_PLUGINS = (
    _spec("lights", status="hub.tests.test_hub.ok_status",
          shortcuts="hub.tests.test_hub.demo_shortcuts", run_shortcut="hub.tests.test_hub.demo_run"),
    _spec("flaky", status="hub.tests.test_hub.failing_status"),
    PluginSpec(id="hidden", app="hidden", status="hub.tests.test_hub.ok_status",
               tiles=(_tile(title="Hidden", modes=OWNER_ONLY),)),
)


@override_settings(HUB_PLUGINS=STATUS_PLUGINS)
class HomeStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()

    def test_status_and_shortcuts_follow_mode(self):
        data = self.client.get("/hub/api/status/").json()
        self.assertEqual(data["mode"], DASHBOARD)
        self.assertEqual(data["status"]["lights"]["text"], "3 lights on")
        self.assertEqual(data["status"]["lights"]["level"], ON)
        self.assertNotIn("hidden", data["status"])
        self.assertEqual([s["id"] for s in data["shortcuts"]], ["movie"])
        self.assertEqual(data["shortcuts"][0]["url"], "/hub/api/shortcut/lights/movie/")

        self.client.force_login(User.objects.create_user("owner"))
        data = self.client.get("/hub/api/status/").json()
        self.assertIn("hidden", data["status"])
        self.assertEqual({s["id"] for s in data["shortcuts"]}, {"movie", "lock_up"})

    def test_failed_hook_serves_last_good_value_as_stale(self):
        self.assertFalse(home_data(DASHBOARD)["status"]["flaky"]["stale"])
        cache.delete("hub:status:flaky")
        HOOK_STATE["fail"] = True
        flaky = home_data(DASHBOARD)["status"]["flaky"]
        self.assertEqual(flaky["text"], "fine")
        self.assertTrue(flaky["stale"])

    def test_failed_hook_without_history_is_left_out(self):
        HOOK_STATE["fail"] = True
        self.assertNotIn("flaky", home_data(DASHBOARD)["status"])

    def test_mode_aware_hook_is_called_and_cached_per_mode(self):
        plugins = (_spec("cams", status="hub.tests.test_hub.mode_status"),)
        with override_settings(HUB_PLUGINS=plugins):
            self.assertEqual(home_data(DASHBOARD)["status"]["cams"]["text"], "dashboard view")
            self.assertEqual(home_data(OWNER)["status"]["cams"]["text"], "owner view")
            self.assertEqual(home_data(DASHBOARD)["status"]["cams"]["text"], "dashboard view")

    def test_slow_hook_does_not_block_the_homepage(self):
        HOOK_STATE["release"] = threading.Event()
        plugins = (_spec("slow", status="hub.tests.test_hub.slow_status"),)
        try:
            with override_settings(HUB_PLUGINS=plugins):
                started = time.monotonic()
                data = home_data(DASHBOARD, timeout=0.2)
            self.assertLess(time.monotonic() - started, 2)
            self.assertNotIn("slow", data["status"])
            self.assertTrue(data["refreshing"])
        finally:
            HOOK_STATE["release"].set()

    def _wait_for_refresh(self, plugin):
        """Let the background refresh finish and land in the cache."""
        HOOK_STATE["gate"].set()
        deadline = time.monotonic() + 5
        while cache.get(f"hub:status:{plugin}") is None and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_slow_hook_serves_last_good_value_while_it_refreshes(self):
        plugins = (_spec("gated", status="hub.tests.test_hub.gated_status"),)
        with override_settings(HUB_PLUGINS=plugins):
            self.assertFalse(home_data(DASHBOARD)["refreshing"])
            cache.delete("hub:status:gated")  # expired
            HOOK_STATE.update(gate=threading.Event(), text="second")
            started = time.monotonic()
            data = home_data(DASHBOARD)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(data["status"]["gated"]["text"], "first")
            self.assertFalse(data["status"]["gated"]["stale"])
            self.assertTrue(data["refreshing"])

            self._wait_for_refresh("gated")
            data = home_data(DASHBOARD)
            self.assertEqual(data["status"]["gated"]["text"], "second")
            self.assertFalse(data["refreshing"])

    def test_failed_background_refresh_marks_last_good_value_stale(self):
        plugins = (_spec("gated", status="hub.tests.test_hub.gated_status"),)
        with override_settings(HUB_PLUGINS=plugins):
            home_data(DASHBOARD)
            cache.delete("hub:status:gated")
            HOOK_STATE.update(gate=threading.Event(), gate_fails=True)
            home_data(DASHBOARD)
            HOOK_STATE["gate"].set()
            deadline = time.monotonic() + 5
            while cache.get("hub:status:gated:failed") is None and time.monotonic() < deadline:
                time.sleep(0.02)
            HOOK_STATE["gate"] = threading.Event()  # the retry is slow too
            try:
                gated = home_data(DASHBOARD)["status"]["gated"]
                self.assertEqual(gated["text"], "first")
                self.assertTrue(gated["stale"])
            finally:
                HOOK_STATE["gate"].set()

    @patch("BlackDiamondHub.views.requests.get")
    def test_homepage_arrives_with_status_and_shortcuts(self, get):
        get.return_value = MagicMock(status_code=200, content=b"")
        response = self.client.get("/")
        data = response.context["hub_home"]
        self.assertEqual(data["status"]["lights"]["text"], "3 lights on")
        self.assertEqual([(s["id"], s["url"]) for s in data["shortcuts"]],
                         [("movie", "/hub/api/shortcut/lights/movie/")])
        self.assertContains(response, 'id="hub-home-data"')


@override_settings(HUB_PLUGINS=STATUS_PLUGINS)
class ShortcutApiTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()

    def test_runs_shortcut_offered_in_mode(self):
        response = self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertEqual(response.json(), {"ok": True, "message": "Enjoy the show"})
        self.assertEqual(HOOK_STATE["ran"], ["movie"])

    def test_running_shortcut_refreshes_status_and_shortcuts(self):
        home_data(DASHBOARD)
        self.assertIsNotNone(cache.get("hub:shortcuts:lights"))
        self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertIsNone(cache.get("hub:status:lights"))
        self.assertIsNone(cache.get("hub:shortcuts:lights"))

    def test_owner_only_shortcut_needs_sign_in(self):
        response = self.client.post("/hub/api/shortcut/lights/lock_up/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("ran", HOOK_STATE)

        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.post("/hub/api/shortcut/lights/lock_up/")
        self.assertEqual(response.status_code, 200)

    def test_unknown_plugin_or_shortcut_is_404(self):
        self.assertEqual(self.client.post("/hub/api/shortcut/nope/movie/").status_code, 404)
        self.assertEqual(self.client.post("/hub/api/shortcut/lights/nope/").status_code, 404)

    def test_requires_post_and_csrf(self):
        self.assertEqual(self.client.get("/hub/api/shortcut/lights/movie/").status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/hub/api/shortcut/lights/movie/").status_code, 403)
        self.assertNotIn("ran", HOOK_STATE)

    def test_handler_failure_returns_502(self):
        HOOK_STATE["run_fails"] = True
        response = self.client.post("/hub/api/shortcut/lights/movie/")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])

    def test_loader_requires_shortcut_handler(self):
        with self.assertRaisesMessage(PluginError, "run_shortcut"):
            validate([PluginSpec(id="a", app="a", shortcuts="a.homepage.shortcuts")])


def rows_status(mode):
    HOOK_STATE["status_calls"] = HOOK_STATE.get("status_calls", 0) + 1
    rows = [StatusRow(id="kitchen", title="Kitchen", detail="Song – Artist",
                      image="https://art.example/a.jpg",
                      actions=(Action("pause", "fa-solid fa-pause", primary=True),
                               Action("next", "fa-solid fa-forward-step")))]
    return Status("1 playing", ON, rows=rows,
                  actions=(Action("pause_all", "fa-solid fa-pause"),), refresh=3)


def rows_run(row_id, action_id, mode):
    HOOK_STATE.setdefault("acted", []).append((row_id, action_id, mode))
    if HOOK_STATE.get("act_fails"):
        raise RuntimeError("speaker gone")
    return "Paused"


ROWS_PLUGINS = (
    _spec("music", status="hub.tests.test_hub.rows_status", run_action="hub.tests.test_hub.rows_run"),
)


class StatusRowsValueTests(SimpleTestCase):
    def test_rows_actions_and_refresh_are_serialized(self):
        value = _status_value(rows_status(DASHBOARD))
        self.assertEqual(value["rows"][0], {
            "id": "kitchen", "title": "Kitchen", "detail": "Song – Artist",
            "image": "https://art.example/a.jpg", "dimmed": False,
            "actions": [{"id": "pause", "icon": "fa-solid fa-pause", "label": "", "primary": True},
                        {"id": "next", "icon": "fa-solid fa-forward-step", "label": "", "primary": False}],
        })
        self.assertEqual([a["id"] for a in value["actions"]], ["pause_all"])
        self.assertEqual(value["refresh"], 3)

    def test_plain_status_has_no_extra_keys(self):
        self.assertEqual(_status_value(Status("on")), {"text": "on", "level": "info"})

    def test_unsafe_images_and_bad_ids_are_dropped_and_refresh_floored(self):
        value = _status_value(Status("x", rows=[
            StatusRow(id="a", title="A", image="javascript:alert(1)"),
            StatusRow(id="b", title="B", image="//evil.example/x.png"),
            StatusRow(id="c", title="C", image="/media/art.jpg"),
            StatusRow(id="bad id", title="Bad"),
        ], actions=(Action("no good", "fa-x"),), refresh=1))
        self.assertEqual([(r["id"], r["image"]) for r in value["rows"]],
                         [("a", ""), ("b", ""), ("c", "/media/art.jpg")])
        self.assertNotIn("actions", value)
        self.assertEqual(value["refresh"], 2)

    def test_rows_must_be_status_rows(self):
        with self.assertRaises(TypeError):
            _status_value(Status("x", rows=[{"id": "a"}]))


@override_settings(HUB_PLUGINS=ROWS_PLUGINS)
class StatusActionApiTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()

    def test_status_carries_action_url_and_short_cache(self):
        data = self.client.get("/hub/api/status/").json()
        self.assertEqual(data["status"]["music"]["action_url"], "/hub/api/action/music/")
        self.assertEqual(data["status"]["music"]["refresh"], 3)
        from hub.status import STATUS_TTL, _status_ttl
        self.assertEqual(_status_ttl(data["status"]["music"]), 3)
        self.assertEqual(_status_ttl({"label": "x"}), STATUS_TTL)

    def test_runs_row_and_tile_actions(self):
        response = self.client.post("/hub/api/action/music/", {"row": "kitchen", "action": "next"})
        self.assertEqual(response.json(), {"ok": True, "message": "Paused"})
        self.client.post("/hub/api/action/music/", {"row": "", "action": "pause_all"})
        self.assertEqual(HOOK_STATE["acted"],
                         [("kitchen", "next", DASHBOARD), ("", "pause_all", DASHBOARD)])

    def test_action_refreshes_status(self):
        home_data(DASHBOARD)
        calls = HOOK_STATE["status_calls"]
        self.client.post("/hub/api/action/music/", {"row": "kitchen", "action": "pause"})
        home_data(DASHBOARD)
        self.assertEqual(HOOK_STATE["status_calls"], calls + 1)

    def test_unoffered_action_is_404(self):
        for row, action in (("kitchen", "pause_all"), ("garage", "pause"), ("", "next")):
            response = self.client.post("/hub/api/action/music/", {"row": row, "action": action})
            self.assertEqual(response.status_code, 404, (row, action))
        self.assertEqual(self.client.post("/hub/api/action/nope/", {"action": "pause"}).status_code, 404)
        self.assertNotIn("acted", HOOK_STATE)

    def test_requires_post_and_csrf(self):
        self.assertEqual(self.client.get("/hub/api/action/music/").status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/hub/api/action/music/", {"action": "pause_all"}).status_code, 403)
        self.assertNotIn("acted", HOOK_STATE)

    def test_handler_failure_returns_502(self):
        HOOK_STATE["act_fails"] = True
        response = self.client.post("/hub/api/action/music/", {"action": "pause_all"})
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])

    def test_loader_requires_status_for_actions(self):
        with self.assertRaisesMessage(PluginError, "run_action without status"):
            validate([PluginSpec(id="a", app="a", run_action="a.homepage.act")])


@override_settings(HUB_PLUGINS=ROWS_PLUGINS, BDH_HUB_UNITS="metric")
class HubUnitsApiTests(TestCase):
    def setUp(self):
        cache.clear()
        HOOK_STATE.clear()
        patcher = patch.object(hub_store, "TTL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def saved(self):
        return AppSetting.objects.filter(app_id="hub", key="units").values_list("value", flat=True).first()

    def test_guest_sets_hub_units(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post("/hub/api/units/", {"units": "imperial"}).status_code, 403)
        strict.get("/")
        token = strict.cookies["csrftoken"].value
        response = strict.post("/hub/api/units/", {"units": "imperial"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.json(), {"ok": True, "units": "imperial"})
        self.assertEqual(self.saved(), "imperial")
        self.assertIsNone(AppSetting.objects.get(app_id="hub", key="units").updated_by)

    def test_rejects_bad_units(self):
        for bad in ("", "kelvin", "IMPERIAL"):
            self.assertEqual(self.client.post("/hub/api/units/", {"units": bad}).status_code, 400, bad)
        self.assertEqual(self.client.get("/hub/api/units/").status_code, 405)
        self.assertIsNone(self.saved())

    def test_change_refreshes_cached_status(self):
        home_data(DASHBOARD)
        calls = HOOK_STATE["status_calls"]
        self.client.post("/hub/api/units/", {"units": "metric"})
        home_data(DASHBOARD)
        self.assertEqual(HOOK_STATE["status_calls"], calls, "an unchanged value keeps the cache")
        self.client.post("/hub/api/units/", {"units": "imperial"})
        home_data(DASHBOARD)
        self.assertEqual(HOOK_STATE["status_calls"], calls + 1)

def demo_stay():
    if HOOK_STATE.get("stay_fails"):
        raise RuntimeError("HA down")
    return HOOK_STATE.get("stay")


LODGE_TZ = timezone(timedelta(hours=-7))
STAY_PLUGINS = (
    *STATUS_PLUGINS,
    PluginSpec(id="stays", app="stays", stay="hub.tests.test_hub.demo_stay"),
)


@override_settings(HUB_PLUGINS=STAY_PLUGINS)
class StayModeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        HOOK_STATE.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        patcher.start().return_value = MagicMock(status_code=200, content=b"")
        self.addCleanup(patcher.stop)
        now = datetime.now(LODGE_TZ)
        self.checkout = (now + timedelta(days=2)).replace(hour=11, minute=0, second=0, microsecond=0)
        HOOK_STATE["stay"] = Stay("The Smiths", now - timedelta(days=1), self.checkout)

    def test_reported_stay_puts_homepage_in_guest_mode_with_welcome(self):
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], GUEST)
        self.assertContains(response, "Welcome, The Smiths")
        c = self.checkout
        self.assertContains(response, f"Checkout {c:%A}, {c:%b} {c.day} at 11 AM")
        self.assertEqual(self.client.get("/hub/api/status/").json()["mode"], GUEST)

    def test_no_stay_is_dashboard_without_welcome(self):
        HOOK_STATE["stay"] = None
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], DASHBOARD)
        self.assertNotContains(response, "hub-welcome\"")

    def test_owner_mode_wins_and_skips_welcome(self):
        self.client.force_login(User.objects.create_user("owner"))
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertNotContains(response, "Welcome, The Smiths")

    def test_failed_hook_keeps_last_stay_until_checkout(self):
        self.assertIsNotNone(current_stay())
        cache.delete("hub:stay:stays")
        HOOK_STATE["stay_fails"] = True
        self.assertEqual(current_stay()["guest"], "The Smiths")
        cache.delete("hub:stay:stays")
        self.assertIsNone(current_stay(now=self.checkout + timedelta(minutes=1)))

    def test_hook_returning_wrong_type_is_ignored(self):
        HOOK_STATE["stay"] = "The Smiths"
        self.assertIsNone(current_stay())

    @override_settings(HUB_OWNER_VISIT_USER="lodge")
    def test_owner_visit_signs_the_hub_in(self):
        User.objects.create_user("lodge")
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        response = self.client.get("/")
        self.assertEqual(response.context["hub_mode"], OWNER)
        self.assertEqual(response.context["user"].username, "lodge")
        self.assertEqual(self.client.get("/hub/api/status/").json()["mode"], OWNER)
        # Not remembered: the hub is back to the dashboard once the visit ends.
        cache.clear()
        HOOK_STATE["stay"] = None
        self.assertEqual(self.client.get("/").context["hub_mode"], DASHBOARD)

    @override_settings(HUB_OWNER_VISIT_USER="lodge")
    def test_guest_stay_or_missing_user_does_not_sign_in(self):
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        cache.clear()
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)

    def test_owner_visit_without_setting_is_guest_mode(self):
        User.objects.create_user("lodge")
        HOOK_STATE["stay"] = Stay("Owner visit", checkout=self.checkout, owner=True)
        self.assertEqual(self.client.get("/").context["hub_mode"], GUEST)


def demo_card():
    return HOOK_STATE.get("card")


CARD_PLUGINS = (
    *STAY_PLUGINS,
    PluginSpec(id="lodge", app="lodge", card="hub.tests.test_hub.demo_card"),
)


@override_settings(HUB_PLUGINS=CARD_PLUGINS)
class LodgeCardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        HOOK_STATE.clear()
        patcher = patch("BlackDiamondHub.views.requests.get")
        patcher.start().return_value = MagicMock(status_code=200, content=b"")
        self.addCleanup(patcher.stop)
        HOOK_STATE["card"] = Card(
            "Vacation mode", "Next: The Smiths",
            readings=(Reading("Inside", 14.5, "C"),),
            alerts=("Fireplace off: didn't complete",),
            url_name="wifi_qr", level=WARN,
        )

    def test_card_with_alerts_and_link_for_dashboard_and_owner(self):
        card = self.client.get("/hub/api/status/").json()["card"]
        self.assertEqual(card["title"], "Vacation mode")
        self.assertEqual(card["readings"], [{"label": "Inside", "value": 14.5, "unit": "C"}])
        self.assertEqual(card["alerts"], ["Fireplace off: didn't complete"])
        self.assertEqual((card["url"], card["level"]), ("/wifi/", WARN))

        response = self.client.get("/")
        self.assertEqual(response.context["hub_card"]["title"], "Vacation mode")
        self.assertContains(response, 'id="hub-card-data"')
        self.assertNotContains(response, 'class="hub-welcome"')

    def test_guests_get_no_alerts_or_link(self):
        HOOK_STATE["stay"] = Stay("The Smiths")
        card = self.client.get("/hub/api/status/").json()["card"]
        self.assertEqual((card["alerts"], card["url"], card["level"]), ([], None, "info"))
        self.assertEqual(card["readings"][0]["label"], "Inside")

    def test_no_card_is_null(self):
        HOOK_STATE["card"] = None
        self.assertIsNone(self.client.get("/hub/api/status/").json()["card"])
