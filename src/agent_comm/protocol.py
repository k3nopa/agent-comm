"""Shared wire-protocol constants and envelope helpers for hub <-> daemon messages."""

from __future__ import annotations

import re
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

DEFAULT_HUB_HOST = "127.0.0.1"
DEFAULT_HUB_PORT = 8765

GROUP_PREFIX = "#"


def is_valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def is_group_target(to: str) -> bool:
    return to.startswith(GROUP_PREFIX)


def group_name_from_target(to: str) -> str:
    return to[len(GROUP_PREFIX) :]


# --- daemon -> hub ---

def msg_connect(name: str) -> dict[str, Any]:
    return {"type": "connect", "name": name}


def msg_send(req_id: str, to: str, body: str) -> dict[str, Any]:
    return {"type": "send", "req_id": req_id, "to": to, "body": body}


def msg_disconnect() -> dict[str, Any]:
    return {"type": "disconnect"}


# --- hub -> daemon ---

def msg_connect_ack(conn_id: str, name: str, peers: list[str]) -> dict[str, Any]:
    return {"type": "connect_ack", "id": conn_id, "name": name, "peers": peers}


def msg_connect_error(reason: str, detail: str = "") -> dict[str, Any]:
    return {"type": "connect_error", "reason": reason, "detail": detail}


def msg_presence(event: str, name: str) -> dict[str, Any]:
    return {"type": "presence", "event": event, "name": name}


def msg_send_ack(
    req_id: str,
    delivered: bool,
    recipients: list[str] | None = None,
    offline: list[str] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {"type": "send_ack", "req_id": req_id, "delivered": delivered}
    if recipients is not None:
        msg["recipients"] = recipients
    if offline is not None:
        msg["offline"] = offline
    return msg


def msg_error(req_id: str | None, code: str, detail: str = "") -> dict[str, Any]:
    return {"type": "error", "req_id": req_id, "code": code, "detail": detail}


def msg_deliver(msg_id: str, sender: str, body: str, ts: str) -> dict[str, Any]:
    return {"type": "deliver", "msg_id": msg_id, "from": sender, "body": body, "ts": ts}
