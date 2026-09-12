"""The hub server: a websocket per connected name, in-memory routing only."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from datetime import UTC, datetime

import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from agent_comm import protocol
from agent_comm.hub.registry import NameTaken, Registry
from agent_comm.paths import cleanup_hub_state, ensure_state_root, hub_pid_file, write_hub_state

logger = logging.getLogger("agent_comm.hub")


class Hub:
    def __init__(self) -> None:
        self.registry: Registry[ServerConnection] = Registry()

    async def _broadcast_presence(self, event: str, name: str) -> None:
        msg = json.dumps(protocol.msg_presence(event, name))
        for peer_name in self.registry.peers(exclude=name):
            reg = self.registry.get(peer_name)
            if reg is None:
                continue
            try:
                await reg.conn.send(msg)
            except ConnectionClosed:
                pass

    async def _handle_connect(self, ws: ServerConnection) -> str | None:
        raw = await ws.recv()
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await ws.send(json.dumps(protocol.msg_connect_error("invalid_name", "malformed connect message")))
            await ws.close()
            return None

        if envelope.get("type") != "connect":
            await ws.send(json.dumps(protocol.msg_connect_error("invalid_name", "expected connect as first message")))
            await ws.close()
            return None

        name = envelope.get("name", "")
        if not protocol.is_valid_name(name):
            await ws.send(json.dumps(protocol.msg_connect_error("invalid_name", f"invalid name: {name!r}")))
            await ws.close()
            return None

        try:
            reg = self.registry.register(name, ws)
        except NameTaken:
            await ws.send(json.dumps(protocol.msg_connect_error("name_taken", f"name already connected: {name}")))
            await ws.close()
            return None

        await ws.send(json.dumps(protocol.msg_connect_ack(reg.conn_id, name, self.registry.peers(exclude=name))))
        await self._broadcast_presence("joined", name)
        logger.info("connected: %s (%s)", name, reg.conn_id)
        return name

    async def _handle_send(self, sender_name: str, envelope: dict) -> dict:
        req_id = envelope.get("req_id")
        to = envelope.get("to", "")
        body = envelope.get("body", "")
        target = self.registry.get(to)
        if target is None:
            return protocol.msg_error(req_id, "unknown_target", f"no such connected name: {to}")
        deliver = protocol.msg_deliver(uuid.uuid4().hex, sender_name, body, datetime.now(UTC).isoformat())
        try:
            await target.conn.send(json.dumps(deliver))
        except ConnectionClosed:
            return protocol.msg_error(req_id, "unknown_target", f"target disconnected: {to}")
        return protocol.msg_send_ack(req_id, True)

    async def handler(self, ws: ServerConnection) -> None:
        name = await self._handle_connect(ws)
        if name is None:
            return
        try:
            async for raw in ws:
                try:
                    envelope = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                msg_type = envelope.get("type")
                if msg_type == "send":
                    response = await self._handle_send(name, envelope)
                    await ws.send(json.dumps(response))
                elif msg_type == "disconnect":
                    break
        except ConnectionClosed:
            pass
        finally:
            self.registry.unregister(name)
            await self._broadcast_presence("left", name)
            logger.info("disconnected: %s", name)


async def run_hub(host: str = protocol.DEFAULT_HUB_HOST, port: int = protocol.DEFAULT_HUB_PORT) -> None:
    hub = Hub()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async with serve(hub.handler, host, port) as server:
        bound_port = server.sockets[0].getsockname()[1]
        write_hub_state(host, bound_port)
        logger.info("agent-comm hub listening on ws://%s:%d", host, bound_port)
        await stop_event.wait()
        logger.info("hub received shutdown signal, closing")


def main(host: str = protocol.DEFAULT_HUB_HOST, port: int = protocol.DEFAULT_HUB_PORT) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ensure_state_root()
    hub_pid_file().write_text(str(os.getpid()))
    try:
        asyncio.run(run_hub(host, port))
    finally:
        cleanup_hub_state()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=protocol.DEFAULT_HUB_HOST)
    parser.add_argument("--port", type=int, default=protocol.DEFAULT_HUB_PORT)
    args = parser.parse_args()
    main(args.host, args.port)
