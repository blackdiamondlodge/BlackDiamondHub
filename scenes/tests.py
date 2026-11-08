from django.test import TestCase, Client
from django.conf import settings
from unittest.mock import patch, MagicMock
import requests
from .views import get_scenes, activate_scene, homeassistant_icon_mapping

class SceneControlTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.mock_scenes_response = [
            {
                "entity_id": "scene.living_room_movie",
                "attributes": {"friendly_name": "Movie Night", "icon": "mdi:movie"},
            },
            {
                "entity_id": "scene.dinner_time",
                "attributes": {"friendly_name": "Dinner Time", "icon": "mdi:silverware-fork-knife"},
            },
        ]

    @patch("requests.get")
    def test_get_scenes_success(self, mock_get):
        """Test fetching scenes from Home Assistant API"""
        mock_get.return_value = MagicMock(status_code=200, json=lambda: self.mock_scenes_response)
        
        with self.settings(SCENE_FILTER=[]):  # No filtering applied
            scenes = get_scenes()
            
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["name"], "Movie Night")
        self.assertEqual(scenes[0]["icon"], "fa-solid fa-film")  # Mapped correctly
        
    @patch("requests.get")
    def test_get_scenes_with_filter(self, mock_get):
        """Test filtering scenes based on SCENE_FILTER"""
        mock_get.return_value = MagicMock(status_code=200, json=lambda: self.mock_scenes_response)
        
        with self.settings(SCENE_FILTER=["dinner time"]):
            scenes = get_scenes()

        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["name"], "Dinner Time")

    @patch("requests.get", side_effect=requests.ConnectionError("unreachable"))
    def test_scenes_page_renders_when_home_assistant_is_unreachable(self, mock_get):
        response = Client().get("/scenes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scenes"], [])

    @patch("requests.post")
    def test_activate_scene(self, mock_post):
        """Test activating a scene by sending request to Home Assistant"""
        mock_post.return_value = MagicMock(status_code=200)
        scene_id = "scene.living_room_movie"
        
        activate_scene(scene_id)
        
        mock_post.assert_called_once_with(
            f"{settings.HOMEASSISTANT_URL}/api/services/scene/turn_on",
            headers={
                "Authorization": f"Bearer {settings.HOMEASSISTANT_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"entity_id": scene_id},
            timeout=10,
        )

    def test_homeassistant_icon_mapping(self):
        """Test that Home Assistant icons map to FontAwesome correctly"""
        self.assertEqual(homeassistant_icon_mapping("mdi:movie"), "fa-solid fa-film")
        self.assertEqual(homeassistant_icon_mapping("mdi:silverware-fork-knife"), "fa-solid fa-utensils")
        self.assertEqual(homeassistant_icon_mapping("mdi:unknown-icon"), "fas fa-question-circle")  # Default case

    @patch("scenes.views.get_scenes")
    def test_scenes_view_get(self, mock_get_scenes):
        """Test GET request to scenes view"""
        mock_get_scenes.return_value = [
            {"id": "scene.living_room_movie", "name": "Movie Night", "icon": "fa-solid fa-film"}
        ]
        
        response = self.client.get("/scenes/")
        
        print(f"Response content: {response}")
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Movie Night")
        self.assertContains(response, "fa-solid fa-film")

    @patch("scenes.views.activate_scene")
    def test_scenes_view_post(self, mock_activate_scene):
        """Test POST request to activate a scene"""
        scene_id = "scene.living_room_movie"
        response = self.client.post("/scenes/", {"scene_id": scene_id})
        
        self.assertEqual(response.status_code, 302)  # Redirect after activation
        mock_activate_scene.assert_called_once_with(scene_id)


class HomepageHookTests(TestCase):
    @patch("scenes.homepage.requests.get")
    def test_status_counts_lights_but_not_groups(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: [
            {"entity_id": "light.a", "state": "on", "attributes": {}},
            {"entity_id": "light.b", "state": "off", "attributes": {}},
            {"entity_id": "light.group", "state": "on", "attributes": {"entity_id": ["light.a"]}},
            {"entity_id": "switch.c", "state": "on", "attributes": {}},
        ])
        from scenes.homepage import status
        self.assertEqual(status().text, "1 light on")

    @patch("scenes.homepage.activate_scene")
    @patch("scenes.homepage.get_scenes")
    def test_scene_shortcuts(self, mock_scenes, mock_activate):
        mock_scenes.return_value = [{"id": "scene.movie", "name": "Movie", "icon": "fas fa-tv"}]
        from scenes.homepage import run_shortcut, shortcuts
        self.assertEqual([s.id for s in shortcuts()], ["movie"])
        run_shortcut("movie")
        mock_activate.assert_called_once_with("scene.movie")