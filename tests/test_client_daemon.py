from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_comm import paths
from agent_comm.client import ipc
from agent_comm.client.daemon import run_daemon
from tests.conftest import RawClient


@pytest.fixture
def daemon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_COMM_HOME", str(tmp_path))
    return tmp_path


async def _start_daemon(name: str, hub_url: str) -> asyncio.Task:
    paths.ensure_state_dir(name)
    task = asyncio.create_task(run_daemon(name, hub_url))
    sock_path = paths.sock_file(name)
    for _ in range(100):
        if sock_path.exists():
            return task
        await asyncio.sleep(0.05)
    raise TimeoutError("daemon did not start in time")


async def _stop_daemon(name: str, task: asyncio.Task) -> None:
    sock_path = str(paths.sock_file(name))
    try:
        await ipc.call(sock_path, {"cmd": "disconnect"}, timeout=2)
    except ipc.DaemonUnreachable:
        pass
    await asyncio.wait_for(task, timeout=2)


async def test_status_reports_peers(hub_url: str, daemon_home: Path) -> None:
    task = await _start_daemon("carol", hub_url)
    sock_path = str(paths.sock_file("carol"))
    try:
        resp = await ipc.call(sock_path, {"cmd": "status"}, timeout=2)
        assert resp["ok"] is True
        assert resp["peers"] == []
        assert resp["inbox_pending"] == 0
    finally:
        await _stop_daemon("carol", task)


async def test_message_arrives_before_wait_is_called(hub_url: str, daemon_home: Path) -> None:
    task = await _start_daemon("dave", hub_url)
    sock_path = str(paths.sock_file("dave"))
    try:
        sender = await RawClient.connect(hub_url, "sender")
        await sender.recv_raw()  # connect_ack (dave is already connected, listed in peers)

        await sender.send_raw({"type": "send", "req_id": "r1", "to": "dave", "body": "early"})
        await sender.recv_raw()  # send_ack

        await asyncio.sleep(0.1)  # ensure it's sitting in the inbox before wait is called

        resp = await asyncio.wait_for(ipc.call(sock_path, {"cmd": "wait", "timeout": 2}), timeout=3)
        assert resp["ok"] is True
        assert resp["from"] == "sender"
        assert resp["msg"] == "early"

        await sender.close()
    finally:
        await _stop_daemon("dave", task)


async def test_wait_times_out_when_no_message(hub_url: str, daemon_home: Path) -> None:
    task = await _start_daemon("erin", hub_url)
    sock_path = str(paths.sock_file("erin"))
    try:
        resp = await asyncio.wait_for(ipc.call(sock_path, {"cmd": "wait", "timeout": 0.3}), timeout=2)
        assert resp == {"ok": True, "timed_out": True}
    finally:
        await _stop_daemon("erin", task)


async def test_multiple_waiters_only_one_gets_the_message(hub_url: str, daemon_home: Path) -> None:
    task = await _start_daemon("frank", hub_url)
    sock_path = str(paths.sock_file("frank"))
    try:
        wait1 = asyncio.create_task(ipc.call(sock_path, {"cmd": "wait", "timeout": 0.5}))
        wait2 = asyncio.create_task(ipc.call(sock_path, {"cmd": "wait", "timeout": 0.5}))
        await asyncio.sleep(0.1)  # let both waiters register against the inbox queue

        sender = await RawClient.connect(hub_url, "sender")
        await sender.recv_raw()  # connect_ack (frank is already connected, listed in peers)
        await sender.send_raw({"type": "send", "req_id": "r1", "to": "frank", "body": "only-one"})
        await sender.recv_raw()  # send_ack

        resp1, resp2 = await asyncio.gather(wait1, wait2)
        results = [resp1, resp2]
        delivered = [r for r in results if r.get("ok") and "msg" in r]
        timed_out = [r for r in results if r.get("timed_out")]

        assert len(delivered) == 1
        assert delivered[0]["msg"] == "only-one"
        assert len(timed_out) == 1

        await sender.close()
    finally:
        await _stop_daemon("frank", task)
