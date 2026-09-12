# agent-comm

A local messaging hub for cross-harness AI agent communication — lets separate
harness processes (Claude Code, [pi agent](https://github.com/earendil-works/pi-coding-agent),
Codex, ...) exchange messages by name while each keeps working independently.

Everything is driven through one CLI, so any harness that can shell out to a
command can participate — no MCP server or native tool-calling API required.

## How it works

- A single **hub** process routes messages between connected names, in memory
  only (no persistence across restarts).
- Each connected name runs a local **daemon** process that holds the real
  connection to the hub and buffers incoming messages into a local inbox.
- The **CLI** talks to its daemon over a Unix socket; `connect` spawns the
  daemon on first use.

Every command prints one JSON object per line to stdout and exits `0` iff
`"ok"` is `true`, so it's easy to parse from a shell-driven harness.

## Install globally

Run once from the repo root so `agent-comm` works from any directory, for any
harness, without `cd`-ing into this repo or using `uv run`:

```bash
uv tool install --editable .
```

This drops a shim on `~/.local/bin` (already on PATH for most setups) backed
by an isolated tool venv importing this repo in editable mode — further edits
to the source take effect immediately, no reinstall needed. Only changes to
`pyproject.toml` itself (new deps, new script entry points) require
`uv tool install --editable . --reinstall`.

## Quick start

```bash
# start the hub once, in the background — it's meant to stay up as a
# long-lived singleton that many harness sessions connect to over time
agent-comm hub start --port 8765
agent-comm hub status

export AGENT_COMM_HUB_URL=ws://127.0.0.1:8765
agent-comm connect alice
agent-comm connect bob      # alice sees bob join via `status`/`peers`

agent-comm send alice --to bob --msg "hello"
agent-comm wait bob --timeout 30      # blocks until a message arrives, or times out
agent-comm poll bob                    # non-blocking drain of the inbox
agent-comm status alice
agent-comm disconnect alice
agent-comm disconnect bob

agent-comm hub stop   # only when you actually want the whole hub down
```

(No global install yet? Every command above also works as `uv run agent-comm
...` from inside the repo.)

## Commands

| Command | Description |
|---|---|
| `agent-comm hub start [--host] [--port] [--foreground\|--background] [--timeout]` | Start the hub. Background (default) redirects its log output to `hub.log`; foreground streams it to the terminal until Ctrl+C. |
| `agent-comm hub stop [--timeout]` | Stop the hub, whichever way it was started. |
| `agent-comm hub status` | Show whether the hub is running, and its pid/host/port. |
| `agent-comm hub restart [--host] [--port] [--foreground\|--background] [--timeout]` | Stop then start, in one call. |
| `agent-comm connect NAME [--hub-url] [--timeout]` | Connect (spawns the local daemon if needed). |
| `agent-comm send NAME --to TARGET --msg TEXT` | Send a message; does not wait for a reply. |
| `agent-comm wait NAME [--timeout]` | Block until a message arrives, or until timeout (`timed_out: true` is a normal result). |
| `agent-comm poll NAME [--max]` | Non-blocking drain of pending messages. |
| `agent-comm disconnect NAME` | Disconnect and stop the local daemon. |
| `agent-comm status NAME` | Show connection id, known peers, and inbox size. |
| `agent-comm group set NAME [MEMBERS...]` | Admin-only: define/replace a group's full membership. |
| `agent-comm group add NAME MEMBERS...` | Admin-only: add member(s) to a group (creates it if new). |
| `agent-comm group remove NAME MEMBERS...` | Admin-only: remove member(s) from a group. |
| `agent-comm group delete NAME` | Admin-only: delete a group entirely. |
| `agent-comm group list` | List all groups and their members. |
| `agent-comm group show NAME` | Show a group's members and which are currently online. |

Config: `AGENT_COMM_HUB_URL` (default `ws://127.0.0.1:8765`), `AGENT_COMM_HOME`
(default `~/.agent-comm`) for daemon state (`daemon.pid`, `daemon.sock`,
`daemon.log` per name) and hub state (`hub.pid`, `hub.log`, `hub.json`,
`hub.sock`). Groups are in-memory only and cleared on every hub restart;
`group` commands reach the hub over `hub.sock`, a separate local-only admin
channel from the public websocket port that `connect`/`send`/etc. use.

## Using it from a harness

**Claude Code**: shell out via the Bash tool, e.g. `uv run --project <path>
agent-comm connect claude-code-1`. For a long blocking `wait`, run it as a
background/subagent task so the main session keeps working.

**pi agent** (or any harness with no backgrounding primitive): prefer
short-timeout polling each turn — `agent-comm wait NAME --timeout 5` or plain
`poll` — since a timeout is a cheap, normal, zero-exit-code result.

Two instances of the *same* harness type can talk to each other the same
way — routing is purely by the name each client picks at connect time, with
no notion of harness type in the protocol.

## Groups (aliases)

A group is a human-managed alias for a set of names — e.g. "devs" = {dev-1,
dev-2} — so one agent can broadcast to all of them without knowing who's in
the group. Group membership is set up manually with `agent-comm group ...`;
it's an admin convenience, never something an agent does to itself — there's
no `join`/self-add command, and agent-facing tooling never calls `group`.
Addressing uses a Slack-style `#` prefix to disambiguate from individual
names with zero ambiguity: `--to bob` is unchanged and always means the
individual "bob"; `--to '#devs'` means the group. Groups are in-memory only
and don't survive a hub restart — redefine them with `group set` afterward.

```
$ agent-comm group set devs dev-1 dev-2
{"ok": true, "group": "devs", "members": ["dev-1", "dev-2"]}

# from a QA agent's session:
$ agent-comm send qa-1 --to '#devs' --msg "regression found in auth.py, please check"
{"ok": true, "delivered": true, "recipients": ["dev-1", "dev-2"], "offline_members": []}

# dev-1 and dev-2 both pick it up the normal way:
$ agent-comm wait dev-1 --timeout 30
{"ok": true, "from": "qa-1", "msg": "regression found in auth.py, please check", "msg_id": "...", "ts": "..."}
```

A group with no currently-connected members is not an error — you get back
`"delivered": false` with an empty `recipients` list, not a failure exit
code. Sending to a name that was never defined as a group at all *is* an
error: `{"ok": false, "error": "unknown_group", ...}`.

## Example: two harnesses end-to-end

A mock of what this looks like once the hub is installed globally and left
running as a shared singleton — a Claude Code session and a pi agent session,
each in their own terminal/process, handing a message back and forth.

```
# one-time, anywhere:
$ uv tool install --editable .

# once, ever (or after a reboot) — leave this running in the background:
$ agent-comm hub start
{"ok": true, "already_running": false, "pid": 41213, "host": "127.0.0.1", "port": 8765, "log_file": "/home/you/.agent-comm/hub.log"}

$ agent-comm hub status
{"ok": true, "running": true, "pid": 41213, "host": "127.0.0.1", "port": 8765}
```

**Claude Code session** (shells out via its Bash tool):

```
$ agent-comm connect claude-code-1
{"ok": true, "id": "a1b2c3...", "name": "claude-code-1", "already_connected": false, "peers": []}

$ agent-comm send claude-code-1 --to pi-agent-1 --msg "starting the refactor on auth.py, will ping when done"
{"ok": false, "error": "unknown_target", "detail": "no such connected name: pi-agent-1"}
# (pi agent hasn't connected yet — try again once it has)
```

**pi agent session** (separate process, shelling out to the same CLI):

```
$ agent-comm connect pi-agent-1
{"ok": true, "id": "d4e5f6...", "name": "pi-agent-1", "already_connected": false, "peers": ["claude-code-1"]}
```

**Back in Claude Code**, now that pi agent is up:

```
$ agent-comm send claude-code-1 --to pi-agent-1 --msg "starting the refactor on auth.py, will ping when done"
{"ok": true, "delivered": true}

# Claude Code hands the long wait to a spawned subagent/background task so the
# main session keeps working:
$ agent-comm wait claude-code-1 --timeout 300
# ... (returns later, once pi agent replies)
```

**pi agent**, polling each turn since it has no long-blocking primitive:

```
$ agent-comm poll pi-agent-1
{"ok": true, "messages": [{"from": "claude-code-1", "msg": "starting the refactor on auth.py, will ping when done", "msg_id": "...", "ts": "..."}]}

$ agent-comm send pi-agent-1 --to claude-code-1 --msg "ack, I'll hold off touching auth.py until you ping"
{"ok": true, "delivered": true}
```

**Claude Code's earlier `wait` call returns:**

```
{"ok": true, "from": "pi-agent-1", "msg": "ack, I'll hold off touching auth.py until you ping", "msg_id": "...", "ts": "..."}
```

**Each session disconnects when its task is done** (the hub itself keeps
running for the next session to use):

```
$ agent-comm disconnect claude-code-1
{"ok": true, "already_disconnected": false}

$ agent-comm disconnect pi-agent-1
{"ok": true, "already_disconnected": false}
```

`agent-comm hub stop` is a separate, deliberate action for when you actually
want the whole thing down — not something either session runs as part of its
own cleanup.

## Development

```bash
uv sync --extra dev
uv run pytest
```
