from __future__ import annotations

from agent_comm.hub.server import Hub
from tests.conftest import RawClient


async def test_group_send_fans_out_to_all_online_members(hub_and_url: tuple[Hub, str]) -> None:
    hub, url = hub_and_url
    dev1 = await RawClient.connect(url, "dev-1")
    await dev1.recv_raw()  # connect_ack
    dev2 = await RawClient.connect(url, "dev-2")
    await dev2.recv_raw()  # connect_ack
    await dev1.recv_raw()  # presence joined for dev-2
    qa = await RawClient.connect(url, "qa")
    await qa.recv_raw()  # connect_ack
    await dev1.recv_raw()  # presence joined for qa
    await dev2.recv_raw()  # presence joined for qa

    hub.groups.set_members("devs", ["dev-1", "dev-2"])

    await qa.send_raw({"type": "send", "req_id": "r1", "to": "#devs", "body": "hello devs"})
    ack = await qa.recv_raw()
    assert ack == {
        "type": "send_ack",
        "req_id": "r1",
        "delivered": True,
        "recipients": ["dev-1", "dev-2"],
        "offline": [],
    }

    d1_msg = await dev1.recv_raw()
    assert d1_msg["type"] == "deliver"
    assert d1_msg["from"] == "qa"
    assert d1_msg["body"] == "hello devs"

    d2_msg = await dev2.recv_raw()
    assert d2_msg["type"] == "deliver"
    assert d2_msg["from"] == "qa"
    assert d2_msg["body"] == "hello devs"

    await dev1.close()
    await dev2.close()
    await qa.close()


async def test_group_send_unknown_group_errors(hub_and_url: tuple[Hub, str]) -> None:
    hub, url = hub_and_url
    qa = await RawClient.connect(url, "qa")
    await qa.recv_raw()

    await qa.send_raw({"type": "send", "req_id": "r1", "to": "#nope", "body": "hi"})
    err = await qa.recv_raw()
    assert err["type"] == "error"
    assert err["code"] == "unknown_group"

    await qa.close()


async def test_group_send_zero_online_members_not_an_error(hub_and_url: tuple[Hub, str]) -> None:
    hub, url = hub_and_url
    hub.groups.set_members("devs", ["dev-1", "dev-2"])  # neither connected

    qa = await RawClient.connect(url, "qa")
    await qa.recv_raw()

    await qa.send_raw({"type": "send", "req_id": "r1", "to": "#devs", "body": "hi"})
    ack = await qa.recv_raw()
    assert ack == {
        "type": "send_ack",
        "req_id": "r1",
        "delivered": False,
        "recipients": [],
        "offline": ["dev-1", "dev-2"],
    }

    await qa.close()


async def test_group_send_partial_offline_reported(hub_and_url: tuple[Hub, str]) -> None:
    hub, url = hub_and_url
    dev1 = await RawClient.connect(url, "dev-1")
    await dev1.recv_raw()
    qa = await RawClient.connect(url, "qa")
    await qa.recv_raw()
    await dev1.recv_raw()  # presence joined for qa

    hub.groups.set_members("devs", ["dev-1", "dev-2"])  # dev-2 never connects

    await qa.send_raw({"type": "send", "req_id": "r1", "to": "#devs", "body": "hi"})
    ack = await qa.recv_raw()
    assert ack == {
        "type": "send_ack",
        "req_id": "r1",
        "delivered": True,
        "recipients": ["dev-1"],
        "offline": ["dev-2"],
    }

    deliver = await dev1.recv_raw()
    assert deliver["type"] == "deliver"

    await dev1.close()
    await qa.close()


async def test_group_send_self_included_gets_own_broadcast(hub_and_url: tuple[Hub, str]) -> None:
    hub, url = hub_and_url
    qa = await RawClient.connect(url, "qa")
    await qa.recv_raw()

    hub.groups.set_members("all-hands", ["qa"])

    await qa.send_raw({"type": "send", "req_id": "r1", "to": "#all-hands", "body": "loop"})

    # deliver arrives before the aggregated ack, same ordering as individual self-send.
    deliver = await qa.recv_raw()
    assert deliver["type"] == "deliver"
    assert deliver["from"] == "qa"
    assert deliver["body"] == "loop"

    ack = await qa.recv_raw()
    assert ack == {
        "type": "send_ack",
        "req_id": "r1",
        "delivered": True,
        "recipients": ["qa"],
        "offline": [],
    }

    await qa.close()
