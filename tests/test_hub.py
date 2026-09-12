from __future__ import annotations

import pytest

from tests.conftest import RawClient


async def test_connect_assigns_distinct_ids(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    ack_a = await alice.recv_raw()
    bob = await RawClient.connect(hub_url, "bob")
    ack_b = await bob.recv_raw()

    assert ack_a["type"] == "connect_ack"
    assert ack_b["type"] == "connect_ack"
    assert ack_a["id"] != ack_b["id"]
    assert ack_b["peers"] == ["alice"]

    await alice.close()
    await bob.close()


async def test_presence_joined_broadcast(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()  # connect_ack

    bob = await RawClient.connect(hub_url, "bob")
    await bob.recv_raw()  # connect_ack

    presence = await alice.recv_raw()
    assert presence == {"type": "presence", "event": "joined", "name": "bob"}

    await alice.close()
    await bob.close()


async def test_send_and_deliver(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()
    bob = await RawClient.connect(hub_url, "bob")
    await bob.recv_raw()
    await alice.recv_raw()  # presence joined for bob

    await alice.send_raw({"type": "send", "req_id": "r1", "to": "bob", "body": "hello"})
    ack = await alice.recv_raw()
    assert ack == {"type": "send_ack", "req_id": "r1", "delivered": True}

    delivered = await bob.recv_raw()
    assert delivered["type"] == "deliver"
    assert delivered["from"] == "alice"
    assert delivered["body"] == "hello"

    await alice.close()
    await bob.close()


async def test_self_send(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()

    await alice.send_raw({"type": "send", "req_id": "r1", "to": "alice", "body": "loopback"})

    # On a self-send, both the "deliver" push and the "send_ack" response travel over
    # the same socket; the deliver is written first by the hub's send handler.
    delivered = await alice.recv_raw()
    assert delivered["type"] == "deliver"
    assert delivered["from"] == "alice"
    assert delivered["body"] == "loopback"

    ack = await alice.recv_raw()
    assert ack == {"type": "send_ack", "req_id": "r1", "delivered": True}

    await alice.close()


async def test_send_unknown_target(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()

    await alice.send_raw({"type": "send", "req_id": "r1", "to": "nobody", "body": "hi"})
    err = await alice.recv_raw()
    assert err["type"] == "error"
    assert err["code"] == "unknown_target"

    await alice.close()


async def test_presence_left_broadcast(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()
    bob = await RawClient.connect(hub_url, "bob")
    await bob.recv_raw()
    await alice.recv_raw()  # presence joined for bob

    await bob.send_raw({"type": "disconnect"})
    presence = await alice.recv_raw()
    assert presence == {"type": "presence", "event": "left", "name": "bob"}

    await alice.close()
    await bob.close()


async def test_duplicate_name_rejected(hub_url: str) -> None:
    alice = await RawClient.connect(hub_url, "alice")
    await alice.recv_raw()

    dup = await RawClient.connect(hub_url, "alice")
    err = await dup.recv_raw()
    assert err == {"type": "connect_error", "reason": "name_taken", "detail": "name already connected: alice"}

    await alice.close()
    await dup.close()


async def test_invalid_name_rejected(hub_url: str) -> None:
    bad = await RawClient.connect(hub_url, "not a valid name!")
    err = await bad.recv_raw()
    assert err["type"] == "connect_error"
    assert err["reason"] == "invalid_name"

    await bad.close()
