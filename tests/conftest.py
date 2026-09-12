from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve

from agent_comm.hub.server import Hub


@pytest.fixture
async def hub_url() -> AsyncIterator[str]:
    hub = Hub()
    server = await serve(hub.handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


class RawClient:
    """A minimal hub client used to drive hub behavior directly in tests,
    bypassing the daemon/CLI layers entirely."""

    def __init__(self, ws) -> None:
        self.ws = ws

    @classmethod
    async def connect(cls, hub_url: str, name: str) -> "RawClient":
        ws = await ws_connect(hub_url)
        client = cls(ws)
        await client.send_raw({"type": "connect", "name": name})
        return client

    async def send_raw(self, envelope: dict) -> None:
        await self.ws.send(json.dumps(envelope))

    async def recv_raw(self, timeout: float = 2.0) -> dict:
        raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        return json.loads(raw)

    async def close(self) -> None:
        await self.ws.close()
