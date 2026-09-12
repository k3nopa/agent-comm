from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_comm.cli.main import cli


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_COMM_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _invoke_json(runner: CliRunner, args: list[str]) -> dict:
    result = runner.invoke(cli, args)
    return json.loads(result.output)


def test_group_set_invalid_group_name_rejected_client_side(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "set", "bad name!", "dev-1"])
    assert payload == {"ok": False, "error": "invalid_name", "detail": "invalid group name: 'bad name!'"}


def test_group_set_invalid_member_name_rejected_client_side(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "set", "devs", "bad member!"])
    assert payload["ok"] is False
    assert payload["error"] == "invalid_name"


def test_group_delete_invalid_name_rejected_client_side(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "delete", "bad name!"])
    assert payload["ok"] is False
    assert payload["error"] == "invalid_name"


def test_group_show_invalid_name_rejected_client_side(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "show", "bad name!"])
    assert payload["ok"] is False
    assert payload["error"] == "invalid_name"


def test_group_set_hub_unreachable(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "set", "devs", "dev-1"])
    assert payload["ok"] is False
    assert payload["error"] == "hub_unreachable"


def test_group_list_hub_unreachable(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["group", "list"])
    assert payload["ok"] is False
    assert payload["error"] == "hub_unreachable"


def _run_cli_subprocess(args: list[str], env: dict) -> dict:
    """Run the CLI as a genuinely separate OS process, same reasoning as the
    equivalent helper in test_cli_hub.py: a real `hub start` spawns a real
    child hub process, and only a fresh top-level process (not this long-lived
    test process) lets that child be reaped by init rather than zombie."""
    result = subprocess.run(
        [sys.executable, "-m", "agent_comm.cli.main", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def test_group_commands_end_to_end_against_real_hub(isolated_home: Path) -> None:
    env = dict(os.environ)
    start_payload = _run_cli_subprocess(["hub", "start", "--port", "0", "--timeout", "5"], env)
    try:
        assert start_payload["ok"] is True

        set_payload = _run_cli_subprocess(["group", "set", "devs", "dev-2", "dev-1"], env)
        assert set_payload == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"]}

        add_payload = _run_cli_subprocess(["group", "add", "devs", "dev-3"], env)
        assert add_payload == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2", "dev-3"]}

        remove_payload = _run_cli_subprocess(["group", "remove", "devs", "dev-3"], env)
        assert remove_payload == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"]}

        show_payload = _run_cli_subprocess(["group", "show", "devs"], env)
        assert show_payload == {"ok": True, "group": "devs", "members": ["dev-1", "dev-2"], "online": []}

        list_payload = _run_cli_subprocess(["group", "list"], env)
        assert list_payload == {"ok": True, "groups": {"devs": ["dev-1", "dev-2"]}}

        delete_payload = _run_cli_subprocess(["group", "delete", "devs"], env)
        assert delete_payload == {"ok": True, "group": "devs", "existed": True}

        show_after_delete = _run_cli_subprocess(["group", "show", "devs"], env)
        assert show_after_delete["ok"] is False
        assert show_after_delete["error"] == "unknown_group"
    finally:
        stop_payload = _run_cli_subprocess(["hub", "stop"], env)
        assert stop_payload["ok"] is True
