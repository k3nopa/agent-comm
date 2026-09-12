from __future__ import annotations

import pytest

from agent_comm.hub.groups import GroupNotFound, GroupStore


def test_set_members_creates_group() -> None:
    store = GroupStore()
    result = store.set_members("devs", ["dev-1", "dev-2"])
    assert result == {"dev-1", "dev-2"}
    assert store.exists("devs")
    assert store.get_members("devs") == {"dev-1", "dev-2"}


def test_set_members_fully_replaces_existing() -> None:
    store = GroupStore()
    store.set_members("devs", ["dev-1", "dev-2"])
    store.set_members("devs", ["dev-3"])
    assert store.get_members("devs") == {"dev-3"}


def test_add_members_creates_if_missing() -> None:
    store = GroupStore()
    result = store.add_members("devs", ["dev-1"])
    assert result == {"dev-1"}


def test_add_members_unions_into_existing() -> None:
    store = GroupStore()
    store.set_members("devs", ["dev-1"])
    result = store.add_members("devs", ["dev-2"])
    assert result == {"dev-1", "dev-2"}


def test_remove_members_raises_on_missing_group() -> None:
    store = GroupStore()
    with pytest.raises(GroupNotFound):
        store.remove_members("nope", ["dev-1"])


def test_remove_members_tolerates_non_member() -> None:
    store = GroupStore()
    store.set_members("devs", ["dev-1"])
    result = store.remove_members("devs", ["dev-2"])  # not a member, no error
    assert result == {"dev-1"}


def test_remove_members_emptied_group_still_exists() -> None:
    store = GroupStore()
    store.set_members("devs", ["dev-1"])
    result = store.remove_members("devs", ["dev-1"])
    assert result == set()
    assert store.exists("devs")
    assert store.get_members("devs") == set()


def test_delete_is_idempotent() -> None:
    store = GroupStore()
    store.set_members("devs", ["dev-1"])
    assert store.delete("devs") is True
    assert store.delete("devs") is False
    assert not store.exists("devs")


def test_get_members_missing_group_returns_none() -> None:
    store = GroupStore()
    assert store.get_members("nope") is None


def test_list_groups_sorted() -> None:
    store = GroupStore()
    store.set_members("qa", ["qa-2", "qa-1"])
    store.set_members("devs", ["dev-2", "dev-1"])
    assert store.list_groups() == {
        "devs": ["dev-1", "dev-2"],
        "qa": ["qa-1", "qa-2"],
    }
