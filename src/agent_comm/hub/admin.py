"""Admin-only IPC vocabulary for hub-singleton group (alias) management,
served over a local unix socket (hub.sock) kept strictly separate from the
public, network-facing websocket port per-name daemons/agents use.

Reuses the same generic agent_comm.ipc transport as per-name daemons, but
speaks a completely distinct, "group_"-prefixed command vocabulary so the two
are never confused, even though the wire transport code is shared.

This is a human/admin CLI concern only (see `agent-comm group ...`) -- never
call this from agent-facing tooling. There is no auth on this socket; it
relies purely on being local-machine-only, same trust boundary as any
per-name daemon.sock.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from agent_comm import protocol

if TYPE_CHECKING:
    from agent_comm.hub.server import Hub


def make_admin_handler(hub: "Hub") -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def handle_request(request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd")
        if cmd == "group_set":
            return _group_set(hub, request)
        if cmd == "group_add":
            return _group_add(hub, request)
        if cmd == "group_remove":
            return _group_remove(hub, request)
        if cmd == "group_delete":
            return _group_delete(hub, request)
        if cmd == "group_list":
            return _group_list(hub)
        if cmd == "group_show":
            return _group_show(hub, request)
        return {"ok": False, "error": "unknown_command", "detail": str(cmd)}

    return handle_request


def _validate_names(group: str, members: list[str]) -> str | None:
    if not protocol.is_valid_name(group):
        return f"invalid group name: {group!r}"
    bad = [m for m in members if not protocol.is_valid_name(m)]
    if bad:
        return f"invalid member name(s): {bad!r}"
    return None


def _group_set(hub: "Hub", request: dict) -> dict:
    group, members = request.get("group", ""), list(request.get("members", []))
    err = _validate_names(group, members)
    if err:
        return {"ok": False, "error": "invalid_name", "detail": err}
    result = hub.groups.set_members(group, members)
    return {"ok": True, "group": group, "members": sorted(result)}


def _group_add(hub: "Hub", request: dict) -> dict:
    group, members = request.get("group", ""), list(request.get("members", []))
    err = _validate_names(group, members)
    if err:
        return {"ok": False, "error": "invalid_name", "detail": err}
    result = hub.groups.add_members(group, members)
    return {"ok": True, "group": group, "members": sorted(result)}


def _group_remove(hub: "Hub", request: dict) -> dict:
    group, members = request.get("group", ""), list(request.get("members", []))
    if not hub.groups.exists(group):
        return {"ok": False, "error": "unknown_group", "detail": f"no such group: {group}"}
    result = hub.groups.remove_members(group, members)
    return {"ok": True, "group": group, "members": sorted(result)}


def _group_delete(hub: "Hub", request: dict) -> dict:
    group = request.get("group", "")
    existed = hub.groups.delete(group)
    return {"ok": True, "group": group, "existed": existed}


def _group_list(hub: "Hub") -> dict:
    return {"ok": True, "groups": hub.groups.list_groups()}


def _group_show(hub: "Hub", request: dict) -> dict:
    group = request.get("group", "")
    members = hub.groups.get_members(group)
    if members is None:
        return {"ok": False, "error": "unknown_group", "detail": f"no such group: {group}"}
    online = sorted(m for m in members if hub.registry.is_connected(m))
    return {"ok": True, "group": group, "members": sorted(members), "online": online}
