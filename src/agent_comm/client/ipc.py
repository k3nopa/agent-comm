"""Unix-domain-socket JSON-lines IPC between the CLI and a per-name daemon."""

from __future__ import annotations

import asyncio
import json
from typing import Any

MAX_LINE = 1_000_000


class DaemonUnreachable(Exception):
    pass


async def call(sock_path: str, request: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    """One-shot request/response over the daemon's unix socket. Used by the CLI."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(sock_path), timeout=5)
    except (FileNotFoundError, ConnectionRefusedError, OSError, asyncio.TimeoutError):
        raise DaemonUnreachable(sock_path) from None

    try:
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout) if timeout else await reader.readline()
        if not line:
            raise DaemonUnreachable(sock_path)
        return json.loads(line)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def serve_ipc(sock_path: str, handle_request):
    """Start a unix-socket server; handle_request(request: dict) -> dict is awaited per line."""

    async def _on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line)
            response = await handle_request(request)
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        except (json.JSONDecodeError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    return await asyncio.start_unix_server(_on_client, path=sock_path)
