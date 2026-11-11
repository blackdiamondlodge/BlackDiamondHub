"""Pop-up alerts: the hub end of ``bdh_sdk.alerts``.

Every hub page opens ``ws/hub/alerts/`` and joins :data:`GROUP`. Apps call
``bdh_sdk.alerts.push``, which lands in :func:`send`, from any thread.

``InMemoryChannelLayer`` queues belong to the server's event loop, so a
``group_send`` from another loop (an app's worker thread) can sit unnoticed
until the server loop next wakes. :func:`send` always hands the send to the
loop the consumers run on, which it learns when a screen connects. With no
screen connected there is nobody to show the alert to, so it is dropped.
"""
import asyncio
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

log = logging.getLogger(__name__)

GROUP = "hub.alerts"

_loop = None


class AlertConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        global _loop
        _loop = asyncio.get_running_loop()
        if self.channel_layer is None:
            await self.close()
            return
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.channel_layer is not None:
            await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def hub_alert(self, event):
        await self.send_json({"type": "alert", **event["alert"]})


def send(alert):
    """``bdh_sdk.alerts`` sender: thread-safe and never blocks."""
    loop, layer = _loop, get_channel_layer()
    if loop is None or loop.is_closed() or layer is None:
        log.debug("no screens connected; dropping alert %s", alert.key)
        return
    message = {"type": "hub.alert", "alert": alert.as_dict()}
    future = asyncio.run_coroutine_threadsafe(layer.group_send(GROUP, message), loop)
    future.add_done_callback(_log_failure)


def _log_failure(future):
    if not future.cancelled() and future.exception() is not None:
        log.warning("alert push failed", exc_info=future.exception())
