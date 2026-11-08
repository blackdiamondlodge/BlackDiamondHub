"""Test-only websocket plugin so hub routing tests don't depend on an app."""
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import path


class EchoConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()


websocket_urlpatterns = [path("ws/test_echo/", EchoConsumer.as_asgi())]
