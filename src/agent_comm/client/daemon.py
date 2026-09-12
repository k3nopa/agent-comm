"""Per-name background daemon: holds the real hub connection, buffers an inbox,
and exposes a local unix-socket IPC server for the CLI to talk to.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from agent_comm import protocol
from agent_comm.client import ipc
from agent_comm.paths import cleanup_state, ensure_state_dir, pid_file, sock_file

logger = logging.getLogger("agent_comm.daemon")


@dataclass
class DaemonState:
    name: str
    conn_id: str = ""
    peers: set[str] = field(default_factory=set)
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    ws: object = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)


async def _hub_read_loop(state: DaemonState) -> None:
    try:
        async for raw in state.ws:
            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            msg_type = envelope.get("type")
            if msg_type == "deliver":
                await state.inbox.put(
                    {
                        "from": envelope.get("from"),
                        "msg": envelope.get("body"),
                        "msg_id": envelope.get("msg_id"),
                        "ts": envelope.get("ts"),
                    }
                )
            elif msg_type == "presence":
                if envelope.get("event") == "joined":
                    state.peers.add(envelope.get("name"))
                else:
                    state.peers.discard(envelope.get("name"))
            elif msg_type in ("send_ack", "error"):
                req_id = envelope.get("req_id")
                fut = state.pending.pop(req_id, None)
                if fut is not None and not fut.done():
                    fut.set_result(envelope)
    except ConnectionClosed:
        logger.info("hub connection closed")
    finally:
        state.shutdown_event.set()


async def _shutdown_daemon(state: DaemonState) -> None:
    try:
        await state.ws.send(json.dumps(protocol.msg_disconnect()))
    except (ConnectionClosed, OSError):
        pass
    try:
        await state.ws.close()
    except OSError:
        pass
    state.shutdown_event.set()


def _make_handler(state: DaemonState):
    async def handle_request(request: dict) -> dict:
        cmd = request.get("cmd")

        if cmd == "status":
            return {
                "ok": True,
                "id": state.conn_id,
                "peers": sorted(state.peers),
                "inbox_pending": state.inbox.qsize(),
            }

        if cmd == "send":
            to = request.get("to", "")
            body = request.get("msg", "")
            timeout = request.get("timeout") or 5
            req_id = uuid.uuid4().hex
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            state.pending[req_id] = fut
            await state.ws.send(json.dumps(protocol.msg_send(req_id, to, body)))
            try:
                response = await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                state.pending.pop(req_id, None)
                return {"ok": False, "error": "timeout", "detail": f"no ack from hub within {timeout}s"}
            if response.get("type") == "send_ack":
                return {"ok": True, "delivered": response.get("delivered", True)}
            return {"ok": False, "error": response.get("code", "error"), "detail": response.get("detail", "")}

        if cmd == "wait":
            timeout = request.get("timeout")
            try:
                if timeout is None:
                    item = await state.inbox.get()
                else:
                    item = await asyncio.wait_for(state.inbox.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return {"ok": True, "timed_out": True}
            return {"ok": True, **item}

        if cmd == "poll":
            max_n = request.get("max") or 100
            messages = []
            while len(messages) < max_n and not state.inbox.empty():
                messages.append(state.inbox.get_nowait())
            return {"ok": True, "messages": messages}

        if cmd == "disconnect":
            asyncio.create_task(_shutdown_daemon(state))
            return {"ok": True, "already_disconnected": False}

        return {"ok": False, "error": "unknown_command", "detail": str(cmd)}

    return handle_request


async def run_daemon(name: str, hub_url: str) -> int:
    try:
        ws = await ws_connect(hub_url)
    except OSError as exc:
        logger.error("cannot reach hub at %s: %s", hub_url, exc)
        cleanup_state(name)
        return 1

    await ws.send(json.dumps(protocol.msg_connect(name)))
    raw = await ws.recv()
    envelope = json.loads(raw)
    if envelope.get("type") != "connect_ack":
        logger.error("connect rejected: %s", envelope.get("reason", envelope))
        await ws.close()
        cleanup_state(name)
        return 1

    state = DaemonState(name=name)
    state.conn_id = envelope["id"]
    state.peers = set(envelope.get("peers", []))
    state.ws = ws

    server = await ipc.serve_ipc(str(sock_file(name)), _make_handler(state))
    read_task = asyncio.create_task(_hub_read_loop(state))
    logger.info("daemon ready: name=%s id=%s", name, state.conn_id)

    await state.shutdown_event.wait()

    server.close()
    await server.wait_closed()
    read_task.cancel()
    try:
        await ws.close()
    except OSError:
        pass
    cleanup_state(name)
    logger.info("daemon exiting: name=%s", name)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("hub_url")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    ensure_state_dir(args.name)
    pid_file(args.name).write_text(str(os.getpid()))

    exit_code = asyncio.run(run_daemon(args.name, args.hub_url))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
