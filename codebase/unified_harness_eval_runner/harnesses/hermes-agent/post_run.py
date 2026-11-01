#!/usr/bin/env python3
"""Post-run harvest for the hermes-agent harness.

hermes-agent (``hermes chat``) persists the full session transcript -- every
user/assistant/tool message, each assistant tool call and each tool result -- in
a SQLite database at ``$HOME/.hermes/state.db`` (HOME is /root in this image).
The conversation lives in two tables:

* ``sessions`` -- one row per session, carrying model, cwd and aggregate token
  counts. ``hermes chat -c`` (the harness's resume flag) continues the SAME
  session, so a container holds a single session that every eval turn appends to.
* ``messages`` -- one row per message, in ``id`` order. ``role`` is
  ``user`` / ``assistant`` / ``tool``. An assistant row carries visible text in
  ``content`` and, when it calls tools, a JSON array in ``tool_calls``
  (``[{id, call_id, function: {name, arguments}}]``, ``arguments`` a JSON
  string). A ``tool`` row holds that call's result in ``content`` with
  ``tool_call_id`` linking back to the assistant's call id and ``tool_name``.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we copy the SQLite DB (plus its WAL/SHM sidecars, since
hermes writes in WAL mode and the newest records live in the uncheckpointed WAL)
out of the container, parse it into the agent-inspect trace shape, and emit it on
stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the
eval's turns BY INDEX, where each eval turn is one ``hermes chat`` / ``hermes
chat -c`` (resume) invocation appended to the SAME session. We split the
persisted conversation into one turn per *user* message, in ``id`` order --
every assistant/tool message up to the next user message belongs to that turn --
which matches how the harness appends per invocation.

Per-turn token usage is left empty: hermes's LLM traffic goes through the eval's
/v1 proxy, so the gateway already attributes every token to this session; the
session's aggregate counts are surfaced in metadata only.
"""
import json
import os
import shutil
import subprocess
import sys
import sqlite3
import tempfile

import yaml

# Standalone script: add the repo root so we can reuse the shared docker binary
# resolver (docker is often a shell alias, not a real binary on PATH).
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
from server import DOCKER

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))


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


def _locate_db(container_name: str) -> str:
    """Return the newest hermes state.db path inside the container, or ''."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME" -type f -name state.db -path "*hermes*" '
            r'-printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-',
        ],
        capture_output=True, text=True, check=False,
    )
    return locate.stdout.strip()


def _copy_db(container_name: str, remote_path: str, workdir: str) -> str:
    """Copy the SQLite DB (and WAL/SHM sidecars) to the host; return local path.

    hermes runs SQLite in WAL mode, so the most recent messages are usually still
    in the ``-wal`` sidecar: copying the bare ``.db`` would miss them. We pull all
    three files and let SQLite replay the WAL on open."""
    local_db = os.path.join(workdir, "state.db")
    copied = subprocess.run(
        [DOCKER, "cp", f"{container_name}:{remote_path}", local_db],
        capture_output=True, text=True, check=False,
    )
    if copied.returncode != 0 or not os.path.isfile(local_db):
        return ""
    for suffix in ("-wal", "-shm"):
        subprocess.run(
            [DOCKER, "cp", f"{container_name}:{remote_path}{suffix}",
             local_db + suffix],
            capture_output=True, text=True, check=False,
        )
    return local_db


def _tool_input_args(arguments) -> list:
    """hermes stores a tool call's function.arguments as a JSON string of params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def _thought(row: sqlite3.Row) -> str:
    """An assistant row's narration/reasoning that precedes its tool calls."""
    parts = []
    for col in ("reasoning_content", "reasoning"):
        val = row[col]
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    content = row["content"]
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    return "\n".join(parts).strip()


def parse_state_db(db_path: str) -> dict:
    """Parse a hermes state.db into the agent-inspect trace shape.

    One container holds a single hermes session that ``-c`` keeps appending to, so
    we take the most-recently-started session and walk its messages in id order. A
    new turn opens at each ``user`` message (the task handed to one ``hermes chat``
    invocation); assistant tool calls become steps whose output is filled in from
    the matching ``tool`` message, and the final tool-less assistant text is the
    turn's agent_response.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        session = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if session is None:
            return {"turns": [], "metadata": {}}
        keys = session.keys()
        metadata = {
            "session_id": session["id"],
            "model": session["model"],
            "cwd": session["cwd"] if "cwd" in keys else None,
            "title": session["title"] if "title" in keys else None,
            "token_usage": {
                "input": session["input_tokens"] if "input_tokens" in keys else None,
                "output": session["output_tokens"] if "output_tokens" in keys else None,
                "cache_read": session["cache_read_tokens"] if "cache_read_tokens" in keys else None,
                "cache_write": session["cache_write_tokens"] if "cache_write_tokens" in keys else None,
                "reasoning": session["reasoning_tokens"] if "reasoning_tokens" in keys else None,
            },
            "api_call_count": session["api_call_count"] if "api_call_count" in keys else None,
        }
        rows = conn.execute(
            "SELECT id, role, content, tool_call_id, tool_calls, tool_name, "
            "reasoning, reasoning_content, finish_reason "
            "FROM messages WHERE session_id = ? ORDER BY id",
            (session["id"],),
        ).fetchall()
    finally:
        conn.close()

    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool_call_id -> step, scoped to the current turn

    def open_turn(agent_input="") -> dict:
        nonlocal calls_by_id
        turn = {
            "turn_id": None,
            "agent_input": agent_input,
            "agent_response": "",
            "steps": [],
            "token_usage": {},
        }
        turns.append(turn)
        calls_by_id = {}
        return turn

    for row in rows:
        role = row["role"]

        if role == "user":
            # Each user message is one `hermes chat` invocation -> a new eval turn.
            current = open_turn(agent_input=(row["content"] or "").strip())
            continue

        if role == "tool":
            step = calls_by_id.get(row["tool_call_id"])
            if step is not None:
                step["tool_output"] = row["content"]
            continue

        if role == "assistant":
            if not current:
                current = open_turn()
            try:
                tool_calls = json.loads(row["tool_calls"]) if row["tool_calls"] else []
            except (json.JSONDecodeError, ValueError):
                tool_calls = []
            if not isinstance(tool_calls, list):
                tool_calls = []

            if tool_calls:
                thought = _thought(row)
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") or {}
                    call_id = tc.get("call_id") or tc.get("id")
                    step = {
                        "id": call_id or tc.get("id"),
                        "tool": fn.get("name") or tc.get("name"),
                        "tool_input_args": _tool_input_args(fn.get("arguments")),
                        "tool_output": None,
                        # Narration before the tool call is the agent's thought;
                        # attach it to the first step so it isn't duplicated.
                        "agent_thought": thought or None,
                    }
                    thought = ""
                    current["steps"].append(step)
                    # tool rows link by tool_call_id, which matches id / call_id.
                    if tc.get("id"):
                        calls_by_id[tc["id"]] = step
                    if call_id and call_id != tc.get("id"):
                        calls_by_id[call_id] = step
            else:
                # A tool-less assistant message is spoken output; keep the latest.
                text = (row["content"] or "").strip()
                if text:
                    current["agent_response"] = text

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    remote_path = _locate_db(container_name)
    if not remote_path:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    workdir = tempfile.mkdtemp(prefix="hermes-traj-")
    try:
        local_db = _copy_db(container_name, remote_path, workdir)
        if not local_db:
            print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
            return
        trajectory = parse_state_db(local_db)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps({"trajectory": trajectory}))


if __name__ == "__main__":
    main()
