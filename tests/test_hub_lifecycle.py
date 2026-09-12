from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_comm import paths
from agent_comm.hub.server import run_hub


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_COMM_HOME", str(tmp_path))
    return tmp_path


async def test_run_hub_shuts_down_cleanly_on_sigterm(isolated_home: Path) -> None:
    task = asyncio.create_task(run_hub("127.0.0.1", 0))

    for _ in range(100):
        if paths.hub_state_file().exists():
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("hub did not become ready in time")

    os.kill(os.getpid(), signal.SIGTERM)

    await asyncio.wait_for(task, timeout=2)


def test_hub_server_main_pid_lifecycle_via_subprocess(isolated_home: Path) -> None:
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent_comm.hub.server", "--host", "127.0.0.1", "--port", "0"],
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if paths.hub_state_file().exists():
                break
            assert proc.poll() is None, "hub subprocess exited early"
            time.sleep(0.05)
        else:
            pytest.fail("hub subprocess did not become ready in time")

        state = json.loads(paths.hub_state_file().read_text())
        assert state["pid"] == proc.pid

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        assert proc.returncode == 0

        assert not paths.hub_pid_file().exists()
        assert not paths.hub_state_file().exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
