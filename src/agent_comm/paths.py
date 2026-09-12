"""Per-name local state directory helpers (~/.agent-comm/<name>/)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def state_root() -> Path:
    return Path(os.environ.get("AGENT_COMM_HOME", Path.home() / ".agent-comm"))


def ensure_state_root() -> Path:
    d = state_root()
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir(name: str) -> Path:
    return state_root() / name


def pid_file(name: str) -> Path:
    return state_dir(name) / "daemon.pid"


def sock_file(name: str) -> Path:
    return state_dir(name) / "daemon.sock"


def log_file(name: str) -> Path:
    return state_dir(name) / "daemon.log"


def ensure_state_dir(name: str) -> Path:
    d = state_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(name: str) -> int | None:
    p = pid_file(name)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def daemon_is_running(name: str) -> bool:
    pid = read_pid(name)
    if pid is None:
        return False
    if not is_process_alive(pid):
        return False
    return sock_file(name).exists()


def cleanup_state(name: str) -> None:
    for f in (pid_file(name), sock_file(name)):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


# --- singleton hub state (as opposed to the per-name helpers above) ---


def hub_pid_file() -> Path:
    return state_root() / "hub.pid"


def hub_log_file() -> Path:
    return state_root() / "hub.log"


def hub_state_file() -> Path:
    return state_root() / "hub.json"


def hub_sock_file() -> Path:
    return state_root() / "hub.sock"


def read_hub_pid() -> int | None:
    p = hub_pid_file()
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def hub_is_running() -> bool:
    pid = read_hub_pid()
    return pid is not None and is_process_alive(pid)


def write_hub_state(host: str, port: int) -> None:
    hub_state_file().write_text(json.dumps({"host": host, "port": port, "pid": os.getpid()}))


def read_hub_state() -> dict | None:
    p = hub_state_file()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def cleanup_hub_state() -> None:
    for f in (hub_pid_file(), hub_state_file(), hub_sock_file()):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
