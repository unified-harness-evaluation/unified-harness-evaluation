#!/usr/bin/env python3
"""Post-run harvest for the mimo-code harness.

mimo-code (@mimo-ai/cli) persists every session to a SQLite database at
``$HOME/.local/share/mimocode/mimocode.db`` (HOME is /root in this image). The
conversation lives in two tables (same architecture as opencode/SST):

* ``message`` -- one row per message. ``data`` is JSON carrying ``role``
  ("user" / "assistant"), ``agent_id`` (column; "main" for the top-level
  conversation, other ids for spawned sub-agents) and, for assistant messages,
  per-message token counts. A single ``mimo run`` invocation writes one *user*
  message followed by one or more *assistant* messages (mimo emits a fresh
  assistant message per LLM step / tool round).
* ``part`` -- ordered fragments belonging to a message (``message_id``).
  ``data.type`` is one of ``text`` (visible user task / assistant narration &
  final answer), ``tool`` (a tool call + its output under ``state``),
  ``reasoning`` (model thinking), ``step-start`` / ``step-finish``
  (token/snapshot bookkeeping) or ``patch`` (file diffs). The user's task text
  lives in a ``text`` part of the user message, not in the message ``data``.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we dump the relevant tables out of the container (via a
small Node script executed with the container's own ``node`` -- the node:22 image
ships ``node:sqlite``, and there is no sqlite3 CLI) and parse them into the
agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the
eval's turns BY INDEX, and each eval turn is one ``mimo run`` / ``mimo run -c``
(resume) invocation appended to the SAME session. We split the persisted
conversation into one turn per *user* message of the main agent, in
chronological order -- every assistant message up to the next user message
belongs to that turn -- which matches how the harness appends per invocation.
Sub-agent messages (agent_id != "main") are skipped so they do not create
spurious turns; the sub-agent's task tool call still appears as a step in the
main conversation.
"""
import json
import os
import subprocess
import sys

import yaml

# Standalone script: add the repo root so we can reuse the shared docker binary
# resolver (docker is often a shell alias, not a real binary on PATH).
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
from server import DOCKER

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))

# Node program (run inside the container with `node -`) that reads mimo-code's
# SQLite DB and dumps the message/part/session rows as a single JSON object.
# node:sqlite is experimental (warns on stderr, which we discard) but stable in
# the node:22 image mimo-code ships in. The live DB (WAL mode) is read in place,
# so SQLite applies the -wal sidecar automatically -- no copy needed.
_DUMP_SCRIPT = r"""
const fs = require("fs");
const candidates = [
  (process.env.HOME || "/root") + "/.local/share/mimocode/mimocode.db",
  "/root/.local/share/mimocode/mimocode.db",
];
let dbPath = candidates.find((p) => { try { return fs.existsSync(p); } catch { return false; } });
if (!dbPath) { process.stdout.write("null"); process.exit(0); }
let DatabaseSync;
try { ({ DatabaseSync } = require("node:sqlite")); }
catch (e) { process.stdout.write("null"); process.exit(0); }
const parseJSON = (s) => { try { return JSON.parse(s); } catch { return null; } };
const db = new DatabaseSync(dbPath, { readOnly: true });
const messages = db.prepare(
  "SELECT id, session_id, agent_id, time_created, data FROM message"
).all().map((m) => {
  const d = parseJSON(m.data) || {};
  return {
    id: m.id, session_id: m.session_id, agent_id: m.agent_id,
    time_created: m.time_created, role: d.role, data: d,
  };
});
const parts = db.prepare(
  "SELECT id, message_id, session_id, time_created, data FROM part"
).all().map((p) => ({
  id: p.id, message_id: p.message_id, time_created: p.time_created,
  data: parseJSON(p.data) || {},
}));
let session = null;
try {
  const s = db.prepare(
    "SELECT id, project_id, title, directory, version FROM session " +
    "ORDER BY time_updated DESC LIMIT 1"
  ).get();
  if (s) session = s;
} catch (e) {}
process.stdout.write(JSON.stringify({ session, messages, parts }));
"""


def _capture_enabled() -> bool:
    """Trajectory capture is a configurable parameter. An env override wins so a
    global runner switch can force it; otherwise fall back to harness.yaml."""
    override = os.environ.get("HARNESS_CAPTURE_TRAJECTORY")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes", "on")
    try:
        config = yaml.safe_load(open(os.path.join(HARNESS_DIR, "harness.yaml"))) or {}
    except (OSError, yaml.YAMLError):
        return False
    return bool(config.get("capture_trajectory"))


def _read_db(container_name: str) -> dict | None:
    """Dump mimo-code's SQLite conversation out of the container as a dict.

    Returns None when no DB / no data is found."""
    proc = subprocess.run(
        [DOCKER, "exec", "-i", container_name, "node", "-"],
        input=_DUMP_SCRIPT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _text_of(part_data: dict) -> str:
    return (part_data.get("text") or "").strip()


def _tool_input_args(state: dict) -> list:
    """mimo-code tool input is a dict of named params under state.input."""
    args = state.get("input")
    if isinstance(args, dict):
        return [{"name": name, "value": value} for name, value in args.items()]
    if args is None:
        return []
    return [{"name": "input", "value": args}]


def _accumulate_tokens(acc: dict, tokens: dict) -> None:
    """Fold a per-step token dict (step-finish part) into the turn accumulator."""
    if not isinstance(tokens, dict):
        return
    acc["input"] += tokens.get("input") or 0
    acc["output"] += tokens.get("output") or 0
    acc["reasoning"] += tokens.get("reasoning") or 0
    cache = tokens.get("cache") or {}
    if isinstance(cache, dict):
        acc["cache_read"] += cache.get("read") or 0
        acc["cache_write"] += cache.get("write") or 0


def parse_db(dump: dict) -> dict:
    """Parse the dumped mimo-code tables into the agent-inspect trace shape.

    Turns are delimited by *user* messages of the main agent in chronological
    order: every assistant message (and its parts) up to the next user message
    belongs to the same turn, matching one ``mimo run`` invocation.
    """
    messages = dump.get("messages") or []
    parts = dump.get("parts") or []
    session = dump.get("session") or {}

    parts_by_message: dict = {}
    for part in parts:
        parts_by_message.setdefault(part.get("message_id"), []).append(part)
    for plist in parts_by_message.values():
        plist.sort(key=lambda p: (p.get("time_created") or 0, p.get("id") or ""))

    # Only the main-agent conversation drives eval turns; sub-agent messages
    # (agent_id != "main") are internal to a task tool call.
    messages = [m for m in messages if (m.get("agent_id") or "main") == "main"]
    messages.sort(key=lambda m: (m.get("time_created") or 0, m.get("id") or ""))

    turns: list = []
    current: dict | None = None
    model_id = None
    provider_id = None

    def open_turn() -> dict:
        turn = {
            "turn_id": None,
            "agent_input": "",
            "agent_response": "",
            "steps": [],
            "token_usage": {
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache_read": 0,
                "cache_write": 0,
            },
        }
        turns.append(turn)
        return turn

    for message in messages:
        role = message.get("role")
        mdata = message.get("data") or {}
        mparts = parts_by_message.get(message.get("id"), [])

        if model_id is None:
            model_id = mdata.get("modelID")
            provider_id = mdata.get("providerID")

        if role == "user":
            current = open_turn()
            current["turn_id"] = message.get("id")
            texts = [
                _text_of(p["data"])
                for p in mparts
                if p["data"].get("type") == "text"
            ]
            current["agent_input"] = "\n".join(t for t in texts if t).strip()
            continue

        if role != "assistant":
            continue
        if current is None:
            # Assistant message with no preceding user message (shouldn't happen);
            # start a turn so nothing is dropped.
            current = open_turn()

        pending_thought: str | None = None
        response_chunks: list = []
        for part in mparts:
            pdata = part["data"]
            ptype = pdata.get("type")
            if ptype == "reasoning":
                thought = _text_of(pdata)
                if thought:
                    pending_thought = thought
            elif ptype == "text":
                text = _text_of(pdata)
                if text:
                    response_chunks.append(text)
            elif ptype == "tool":
                state = pdata.get("state") or {}
                output = state.get("output")
                if output is None and isinstance(state.get("error"), str):
                    output = state["error"]
                current["steps"].append({
                    "id": pdata.get("callID") or part.get("id"),
                    "tool": pdata.get("tool"),
                    "tool_input_args": _tool_input_args(state),
                    "tool_output": output,
                    "agent_thought": pending_thought,
                })
                pending_thought = None
            elif ptype == "step-finish":
                _accumulate_tokens(current["token_usage"], pdata.get("tokens") or {})

        if response_chunks:
            joined = "\n".join(response_chunks).strip()
            current["agent_response"] = (
                (current["agent_response"] + "\n" + joined).strip()
                if current["agent_response"]
                else joined
            )

    for turn in turns:
        tu = turn["token_usage"]
        tu["total"] = tu["input"] + tu["output"] + tu["reasoning"]

    metadata = {}
    if isinstance(session, dict) and session:
        metadata = {
            "session_id": session.get("id"),
            "project_id": session.get("project_id"),
            "title": session.get("title"),
            "directory": session.get("directory"),
            "cli_version": session.get("version"),
            "model": model_id,
            "model_provider": provider_id,
        }
    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    dump = _read_db(container_name)
    if not dump or not dump.get("messages"):
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_db(dump)}))


if __name__ == "__main__":
    main()
