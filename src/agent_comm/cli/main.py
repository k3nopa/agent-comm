"""agent-comm CLI: connect / send / wait / poll / disconnect / status / hub.

Every command prints exactly one JSON object per line to stdout; exit code is
0 iff "ok" is true in that JSON, nonzero otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import click

from agent_comm import protocol
from agent_comm.client import ipc
from agent_comm.paths import (
    cleanup_hub_state,
    cleanup_state,
    daemon_is_running,
    ensure_state_dir,
    ensure_state_root,
    hub_is_running,
    hub_log_file,
    hub_state_file,
    is_process_alive,
    log_file,
    read_hub_pid,
    read_hub_state,
    sock_file,
)


def _emit(payload: dict) -> None:
    click.echo(json.dumps(payload))
    if not payload.get("ok", False):
        sys.exit(1)


def _default_hub_url() -> str:
    return os.environ.get(
        "AGENT_COMM_HUB_URL", f"ws://{protocol.DEFAULT_HUB_HOST}:{protocol.DEFAULT_HUB_PORT}"
    )


def _spawn_daemon(name: str, hub_url: str) -> subprocess.Popen:
    ensure_state_dir(name)
    log_f = open(log_file(name), "a")
    return subprocess.Popen(
        [sys.executable, "-m", "agent_comm.client.daemon", name, hub_url],
        stdout=log_f,
        stderr=log_f,
        start_new_session=True,
    )


def _wait_for_socket(name: str, proc: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    path = sock_file(name)
    while time.monotonic() < deadline:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.1)
    return path.exists()


def _spawn_hub(host: str, port: int) -> subprocess.Popen:
    ensure_state_root()
    log_f = open(hub_log_file(), "a")
    return subprocess.Popen(
        [sys.executable, "-m", "agent_comm.hub.server", "--host", host, "--port", str(port)],
        stdout=log_f,
        stderr=log_f,
        start_new_session=True,
    )


def _wait_for_hub_ready(proc: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    path = hub_state_file()
    while time.monotonic() < deadline:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.1)
    return path.exists()


def _stop_hub(timeout: float) -> dict:
    pid = read_hub_pid()
    if pid is None or not is_process_alive(pid):
        cleanup_hub_state()
        return {"was_running": False, "pid": None}

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            cleanup_hub_state()
            return {"was_running": True, "pid": pid}
        time.sleep(0.1)
    raise TimeoutError(f"hub pid {pid} did not exit within {timeout}s")


@click.group()
def cli() -> None:
    pass


@cli.group()
def hub() -> None:
    """Control the singleton hub server."""


@hub.command("start")
@click.option("--host", default=protocol.DEFAULT_HUB_HOST, show_default=True)
@click.option("--port", default=protocol.DEFAULT_HUB_PORT, type=int, show_default=True)
@click.option("--foreground/--background", default=False, show_default=True)
@click.option("--timeout", default=5.0, type=float, show_default=True)
def hub_start(host: str, port: int, foreground: bool, timeout: float) -> None:
    if hub_is_running():
        state = read_hub_state() or {}
        _emit(
            {
                "ok": True,
                "already_running": True,
                "pid": read_hub_pid(),
                "host": state.get("host", host),
                "port": state.get("port", port),
            }
        )
        return

    if foreground:
        from agent_comm.hub.server import main as hub_main

        try:
            hub_main(host, port)
        except OSError as exc:
            _emit({"ok": False, "error": "bind_failed", "detail": str(exc)})
            return
        _emit({"ok": True, "already_running": False, "stopped": True})
        return

    proc = _spawn_hub(host, port)
    if not _wait_for_hub_ready(proc, timeout):
        _emit(
            {
                "ok": False,
                "error": "hub_failed_to_start",
                "detail": f"hub did not become ready, see {hub_log_file()}",
            }
        )
        return

    state = read_hub_state() or {}
    _emit(
        {
            "ok": True,
            "already_running": False,
            "pid": read_hub_pid(),
            "host": state.get("host", host),
            "port": state.get("port", port),
            "log_file": str(hub_log_file()),
        }
    )


@hub.command("stop")
@click.option("--timeout", default=5.0, type=float, show_default=True)
def hub_stop(timeout: float) -> None:
    try:
        result = _stop_hub(timeout)
    except TimeoutError as exc:
        _emit({"ok": False, "error": "stop_timeout", "detail": str(exc)})
        return
    _emit({"ok": True, "already_stopped": not result["was_running"], "pid": result["pid"]})


@hub.command("status")
def hub_status() -> None:
    pid = read_hub_pid()
    if pid is None or not is_process_alive(pid):
        _emit({"ok": True, "running": False})
        return
    state = read_hub_state() or {}
    _emit({"ok": True, "running": True, "pid": pid, "host": state.get("host"), "port": state.get("port")})


@hub.command("restart")
@click.option("--host", default=protocol.DEFAULT_HUB_HOST, show_default=True)
@click.option("--port", default=protocol.DEFAULT_HUB_PORT, type=int, show_default=True)
@click.option("--foreground/--background", default=False, show_default=True)
@click.option("--timeout", default=5.0, type=float, show_default=True)
def hub_restart(host: str, port: int, foreground: bool, timeout: float) -> None:
    try:
        stop_result = _stop_hub(timeout)
    except TimeoutError as exc:
        _emit({"ok": False, "error": "stop_timeout", "detail": str(exc)})
        return

    if foreground:
        from agent_comm.hub.server import main as hub_main

        try:
            hub_main(host, port)
        except OSError as exc:
            _emit({"ok": False, "error": "bind_failed", "detail": str(exc)})
            return
        _emit({"ok": True, "stopped_previous": stop_result["was_running"], "stopped": True})
        return

    proc = _spawn_hub(host, port)
    if not _wait_for_hub_ready(proc, timeout):
        _emit(
            {
                "ok": False,
                "error": "hub_failed_to_start",
                "detail": f"hub did not become ready, see {hub_log_file()}",
            }
        )
        return

    state = read_hub_state() or {}
    _emit(
        {
            "ok": True,
            "stopped_previous": stop_result["was_running"],
            "pid": read_hub_pid(),
            "host": state.get("host", host),
            "port": state.get("port", port),
            "log_file": str(hub_log_file()),
        }
    )


@cli.command()
@click.argument("name")
@click.option("--hub-url", default=None)
@click.option("--timeout", default=5.0, type=float, show_default=True)
def connect(name: str, hub_url: str | None, timeout: float) -> None:
    if not protocol.is_valid_name(name):
        _emit({"ok": False, "error": "invalid_name", "detail": f"invalid name: {name!r}"})
        return

    hub_url = hub_url or _default_hub_url()
    sock_path = str(sock_file(name))

    if daemon_is_running(name):
        try:
            resp = asyncio.run(ipc.call(sock_path, {"cmd": "status"}, timeout=timeout))
        except ipc.DaemonUnreachable:
            cleanup_state(name)
        else:
            _emit(
                {
                    "ok": True,
                    "id": resp.get("id"),
                    "name": name,
                    "already_connected": True,
                    "peers": resp.get("peers", []),
                }
            )
            return

    proc = _spawn_daemon(name, hub_url)
    if not _wait_for_socket(name, proc, timeout):
        _emit(
            {
                "ok": False,
                "error": "hub_unreachable",
                "detail": f"daemon failed to start, see {log_file(name)}",
            }
        )
        return

    try:
        resp = asyncio.run(ipc.call(sock_path, {"cmd": "status"}, timeout=timeout))
    except ipc.DaemonUnreachable:
        _emit({"ok": False, "error": "hub_unreachable", "detail": "daemon started but is not responding"})
        return

    _emit(
        {
            "ok": True,
            "id": resp.get("id"),
            "name": name,
            "already_connected": False,
            "peers": resp.get("peers", []),
        }
    )


@cli.command()
@click.argument("name")
@click.option("--to", "to", required=True)
@click.option("--msg", "msg", required=True)
@click.option("--timeout", default=5.0, type=float, show_default=True)
def send(name: str, to: str, msg: str, timeout: float) -> None:
    sock_path = str(sock_file(name))
    try:
        resp = asyncio.run(
            ipc.call(sock_path, {"cmd": "send", "to": to, "msg": msg, "timeout": timeout}, timeout=timeout + 2)
        )
    except ipc.DaemonUnreachable:
        _emit({"ok": False, "error": "daemon_unreachable", "detail": f"no running daemon for {name}"})
        return
    _emit(resp)


@cli.command(name="wait")
@click.argument("name")
@click.option("--timeout", default=None, type=float)
def wait_(name: str, timeout: float | None) -> None:
    sock_path = str(sock_file(name))
    ipc_timeout = (timeout + 5) if timeout is not None else None
    try:
        resp = asyncio.run(ipc.call(sock_path, {"cmd": "wait", "timeout": timeout}, timeout=ipc_timeout))
    except ipc.DaemonUnreachable:
        _emit({"ok": False, "error": "daemon_unreachable", "detail": f"no running daemon for {name}"})
        return
    _emit(resp)


@cli.command()
@click.argument("name")
@click.option("--max", "max_n", default=100, type=int, show_default=True)
def poll(name: str, max_n: int) -> None:
    sock_path = str(sock_file(name))
    try:
        resp = asyncio.run(ipc.call(sock_path, {"cmd": "poll", "max": max_n}, timeout=5))
    except ipc.DaemonUnreachable:
        _emit({"ok": False, "error": "daemon_unreachable", "detail": f"no running daemon for {name}"})
        return
    _emit(resp)


@cli.command()
@click.argument("name")
def disconnect(name: str) -> None:
    sock_path = str(sock_file(name))
    try:
        resp = asyncio.run(ipc.call(sock_path, {"cmd": "disconnect"}, timeout=5))
    except ipc.DaemonUnreachable:
        _emit({"ok": True, "already_disconnected": True})
        return
    _emit(resp)


@cli.command()
@click.argument("name")
def status(name: str) -> None:
    sock_path = str(sock_file(name))
    try:
        resp = asyncio.run(ipc.call(sock_path, {"cmd": "status"}, timeout=5))
    except ipc.DaemonUnreachable:
        _emit({"ok": True, "connected": False})
        return
    _emit({"ok": True, "connected": True, **{k: v for k, v in resp.items() if k != "ok"}})


if __name__ == "__main__":
    cli()
