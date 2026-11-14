"""
ASGI config for BlackDiamondHub project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BlackDiamondHub.settings')

# Set up Django before importing anything that touches models (consumers).
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.urls import path  # noqa: E402

from hub.alerts import AlertConsumer  # noqa: E402
from hub.loader import websocket_urlpatterns  # noqa: E402
from hub.remote import RemoteConsumer  # noqa: E402

core_websocket_urlpatterns = [
    path("ws/hub/alerts/", AlertConsumer.as_asgi()),
    path("ws/hub/remote/", RemoteConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(core_websocket_urlpatterns + websocket_urlpatterns())
        )
    ),
})
