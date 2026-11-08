from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.utils.module_loading import import_string

from hub.spotify_auth import spotify_token


class SpotifyAuthHooksTests(SimpleTestCase):
    def _request(self, session):
        request = RequestFactory().get("/")
        request.session = session
        return request

    def test_context_flags_spotify_token(self):
        self.assertEqual(spotify_token(self._request({"spotify_token_info": {}})),
                         {"has_spotify_token": True})
        self.assertEqual(spotify_token(self._request({})),
                         {"has_spotify_token": False})

    def test_core_settings_reference_importable_hooks(self):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertIn("hub.spotify_auth.spotify_token", processors)
        for dotted in (*processors, *settings.SOCIAL_AUTH_DISCONNECT_PIPELINE):
            import_string(dotted)
