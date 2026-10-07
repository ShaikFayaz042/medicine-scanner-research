import asyncio
import json
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: dict[str, Any] | Any):
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        message = json.dumps(payload, default=str)

        async with self._lock:
            dead_clients: list[WebSocket] = []
            for client in list(self._clients):
                try:
                    await client.send_text(message)
                except Exception:
                    dead_clients.append(client)
            for client in dead_clients:
                self._clients.discard(client)


manager = WebSocketManager()
broadcast = manager.broadcast
