import asyncio
import json

class EventBus:
    def __init__(self, ws_manager):
        self.ws_manager = ws_manager
        self._loop = None
        # Ghost Handler Desktop (M2): in-process observers for the native
        # shell. Additive only — the websocket broadcast path is unchanged.
        self.subscribers = []

    def set_loop(self, loop):
        self._loop = loop  #store the main event loop

    async def publish(self, event: dict):
        for cb in tuple(self.subscribers):
            try:
                cb(event)
            except Exception as e:
                print("EventBus subscriber error:", e)
        try:
            await self.ws_manager.broadcast(json.dumps(event))
        except Exception as e:
            print("EventBus error:", e)

    def publish_sync(self, event: dict):
        # schedule on main loop without blocking dispatcher thread
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.publish(event), self._loop)
        