from __future__ import annotations

from pathlib import Path

import pytest

from agent_comm import ipc
from agent_comm.hub.admin import make_admin_handler
from agent_comm.hub.server import Hub


@pytest.fixture
async def admin_sock(tmp_path: Path):
    hub = Hub()
    sock_path = str(tmp_path / "hub.sock")
    server = await ipc.serve_ipc(sock_path, make_admin_handler(hub))
    try:
        yield hub, sock_path
    finally:
        server.close()
        await server.wait_closed()


async def test_group_set(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-2", "dev-1"]})
    assert resp == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"]}


async def test_group_add(admin_sock) -> None:
    _, sock_path = admin_sock
    await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-1"]})
    resp = await ipc.call(sock_path, {"cmd": "group_add", "group": "devs", "members": ["dev-2"]})
    assert resp == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"]}


async def test_group_remove(admin_sock) -> None:
    _, sock_path = admin_sock
    await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-1", "dev-2"]})
    resp = await ipc.call(sock_path, {"cmd": "group_remove", "group": "devs", "members": ["dev-2"]})
    assert resp == {"ok": True, "group": "devs", "members": ["dev-1"]}


async def test_group_remove_unknown_group(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "group_remove", "group": "nope", "members": ["dev-1"]})
    assert resp == {"ok": False, "error": "unknown_group", "detail": "no such group: nope"}


async def test_group_delete(admin_sock) -> None:
    _, sock_path = admin_sock
    await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-1"]})
    resp1 = await ipc.call(sock_path, {"cmd": "group_delete", "group": "devs"})
    assert resp1 == {"ok": True, "group": "devs", "existed": True}
    resp2 = await ipc.call(sock_path, {"cmd": "group_delete", "group": "devs"})
    assert resp2 == {"ok": True, "group": "devs", "existed": False}


async def test_group_list(admin_sock) -> None:
    _, sock_path = admin_sock
    await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-1"]})
    await ipc.call(sock_path, {"cmd": "group_set", "group": "qa", "members": ["qa-1"]})
    resp = await ipc.call(sock_path, {"cmd": "group_list"})
    assert resp == {"ok": True, "groups": {"devs": ["dev-1"], "qa": ["qa-1"]}}


async def test_group_show_unknown_group(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "group_show", "group": "nope"})
    assert resp == {"ok": False, "error": "unknown_group", "detail": "no such group: nope"}


async def test_group_show_reports_online_members(admin_sock) -> None:
    hub, sock_path = admin_sock
    await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["dev-1", "dev-2"]})

    hub.registry.register("dev-1", object())  # simulate a live connection

    resp = await ipc.call(sock_path, {"cmd": "group_show", "group": "devs"})
    assert resp == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"], "online": ["dev-1"]}


async def test_group_set_invalid_group_name(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "group_set", "group": "bad name!", "members": []})
    assert resp["ok"] is False
    assert resp["error"] == "invalid_name"


async def test_group_set_invalid_member_name(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "group_set", "group": "devs", "members": ["bad member!"]})
    assert resp["ok"] is False
    assert resp["error"] == "invalid_name"


async def test_unknown_command(admin_sock) -> None:
    _, sock_path = admin_sock
    resp = await ipc.call(sock_path, {"cmd": "not_a_real_command"})
    assert resp == {"ok": False, "error": "unknown_command", "detail": "not_a_real_command"}
