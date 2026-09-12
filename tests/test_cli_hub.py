from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_comm import paths
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


def test_hub_status_when_not_running(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["hub", "status"])
    assert payload == {"ok": True, "running": False}


def test_hub_stop_when_not_running(isolated_home: Path, runner: CliRunner) -> None:
    payload = _invoke_json(runner, ["hub", "stop"])
    assert payload == {"ok": True, "already_stopped": True, "pid": None}


def test_hub_start_already_running(isolated_home: Path, runner: CliRunner) -> None:
    paths.ensure_state_root()
    paths.hub_pid_file().write_text(str(os.getpid()))
    paths.write_hub_state("127.0.0.1", 9999)

    payload = _invoke_json(runner, ["hub", "start", "--port", "9999"])

    assert payload["ok"] is True
    assert payload["already_running"] is True
    assert payload["pid"] == os.getpid()
    assert payload["port"] == 9999


def _run_cli_subprocess(args: list[str], env: dict) -> dict:
    """Run the CLI as a genuinely separate OS process (mirrors real usage, where
    every invocation is its own short-lived process and the hub subprocess a
    `start` spawns gets orphaned to init rather than staying a child of the test
    process itself). Using CliRunner in-process for a spawn+stop round trip would
    leave the spawned hub as a zombie until *this test process* reaps it, since
    it — not init — remains its real parent for the test's whole lifetime.
    """
    result = subprocess.run(
        [sys.executable, "-m", "agent_comm.cli.main", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def test_hub_start_stop_real_process_end_to_end(isolated_home: Path) -> None:
    env = dict(os.environ)
    start_payload = _run_cli_subprocess(["hub", "start", "--port", "0", "--timeout", "5"], env)
    try:
        assert start_payload["ok"] is True
        assert start_payload["already_running"] is False
        pid = start_payload["pid"]
        assert paths.is_process_alive(pid)

        status_payload = _run_cli_subprocess(["hub", "status"], env)
        assert status_payload == {
            "ok": True,
            "running": True,
            "pid": pid,
            "host": "127.0.0.1",
            "port": start_payload["port"],
        }
    finally:
        stop_payload = _run_cli_subprocess(["hub", "stop"], env)
        assert stop_payload["ok"] is True

    assert not paths.hub_pid_file().exists()
    assert not paths.hub_state_file().exists()
