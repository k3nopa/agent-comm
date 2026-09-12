from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_comm import paths


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_COMM_HOME", str(tmp_path))
    return tmp_path


def test_write_and_read_hub_state_roundtrip(isolated_home: Path) -> None:
    paths.ensure_state_root()
    paths.write_hub_state("127.0.0.1", 8765)

    state = paths.read_hub_state()
    assert state == {"host": "127.0.0.1", "port": 8765, "pid": os.getpid()}


def test_read_hub_state_missing(isolated_home: Path) -> None:
    assert paths.read_hub_state() is None


def test_hub_is_running_true_for_current_process(isolated_home: Path) -> None:
    paths.ensure_state_root()
    paths.hub_pid_file().write_text(str(os.getpid()))
    assert paths.hub_is_running() is True


def test_hub_is_running_false_for_dead_pid(isolated_home: Path) -> None:
    paths.ensure_state_root()
    # A pid essentially guaranteed not to be alive.
    paths.hub_pid_file().write_text("999999999")
    assert paths.hub_is_running() is False


def test_hub_is_running_false_when_no_pid_file(isolated_home: Path) -> None:
    assert paths.hub_is_running() is False


def test_cleanup_hub_state_is_safe_noop(isolated_home: Path) -> None:
    paths.cleanup_hub_state()  # should not raise even though nothing exists yet
    assert not paths.hub_pid_file().exists()
    assert not paths.hub_state_file().exists()


def test_cleanup_hub_state_removes_files(isolated_home: Path) -> None:
    paths.ensure_state_root()
    paths.hub_pid_file().write_text(str(os.getpid()))
    paths.write_hub_state("127.0.0.1", 8765)
    paths.hub_sock_file().write_text("")  # stand-in for a real unix socket file

    paths.cleanup_hub_state()

    assert not paths.hub_pid_file().exists()
    assert not paths.hub_state_file().exists()
    assert not paths.hub_sock_file().exists()
