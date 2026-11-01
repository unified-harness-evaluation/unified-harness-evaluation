#!/usr/bin/env python3
"""Post-run harvest for the goose harness.

Block's goose persists the full session transcript (every user/assistant message,
tool request, tool result and per-inference token usage) in a SQLite database at
``$HOME/.local/share/goose/sessions/sessions.db`` (``messages`` table, one row per
message, ``content_json`` holding typed content blocks). Multi-turn conversations
resume the SAME session (``goose run ... --resume`` with no name resumes the latest
session), so every eval turn's messages are appended, in order, to that one session.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we copy the SQLite DB (plus its WAL/SHM sidecars, since
goose writes in WAL mode and the newest records live in the uncheckpointed WAL)
out of the container, parse it into the agent-inspect trace shape, and emit it on
stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared code merges steps into the eval's turns BY INDEX, where
each eval turn is one ``goose run`` invocation. Each invocation injects a fresh
user task message (``userVisible`` text, no ``turnContext`` flag) followed by a
``<turn-context>`` scaffolding message; we therefore start a new turn at every
non-turnContext user *text* message, so N invocations yield N turns in order.
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
    """Return the newest goose sessions.db path inside the container, or ''."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME" -type f -name sessions.db -path "*goose*" '
            r'-printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-',
        ],
        capture_output=True, text=True, check=False,
    )
    return locate.stdout.strip()


def _copy_db(container_name: str, remote_path: str, workdir: str) -> str:
    """Copy the SQLite DB (and WAL/SHM sidecars) to the host; return local path.

    goose runs SQLite in WAL mode, so the most recent messages are usually still
    in the ``-wal`` sidecar: copying the bare ``.db`` would miss them. We pull all
    three files and let SQLite replay the WAL on open."""
    local_db = os.path.join(workdir, "sessions.db")
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
    """goose stores a toolCall's arguments as a JSON object of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def _tool_result_text(tool_response: dict):
    """Flatten a toolResponse's result content into text (or a fallback)."""
    result = (tool_response.get("toolResult") or {}).get("value") or {}
    parts = []
    for chunk in result.get("content") or []:
        if isinstance(chunk, dict) and chunk.get("type") == "text":
            parts.append(chunk.get("text", ""))
    if parts:
        return "\n".join(p for p in parts if p)
    # structured-only results (e.g. shell stdout/stderr/exit_code)
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    return None


def _text_blocks(content: list) -> str:
    return "\n".join(
        b.get("text", "").strip()
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
    ).strip()


def parse_sessions_db(db_path: str) -> dict:
    """Parse a goose sessions.db into the agent-inspect trace shape.

    One container holds a single goose session that ``--resume`` keeps appending
    to, so we take the most-recently-updated session and walk its messages in id
    order. A new turn opens at each non-turnContext user *text* message (the task
    handed to one ``goose run`` invocation); toolResponse user messages and
    ``<turn-context>`` scaffolding attach to the current turn instead.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        session = conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC, created_at DESC LIMIT 1"
        ).fetchone()
        if session is None:
            return {"turns": [], "metadata": {}}
        metadata = {
            "session_id": session["id"],
            "session_name": session["name"],
            "working_dir": session["working_dir"],
            "provider_name": session["provider_name"],
            "total_tokens": session["total_tokens"],
            "accumulated_total_tokens": session["accumulated_total_tokens"],
        }
        try:
            model_cfg = json.loads(session["model_config_json"] or "{}")
            metadata["model"] = model_cfg.get("model_name")
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        rows = conn.execute(
            "SELECT role, content_json, metadata_json FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session["id"],),
        ).fetchall()
    finally:
        conn.close()

    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool id -> step, scoped to the current turn

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
        try:
            content = json.loads(row["content_json"]) or []
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(content, list):
            continue
        try:
            meta = json.loads(row["metadata_json"] or "{}") or {}
        except (json.JSONDecodeError, ValueError):
            meta = {}
        role = row["role"]

        if role == "user":
            tool_responses = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "toolResponse"
            ]
            if tool_responses:
                for tr in tool_responses:
                    step = calls_by_id.get(tr.get("id"))
                    if step is not None:
                        step["tool_output"] = _tool_result_text(tr)
                continue
            # <turn-context> scaffolding is harness-injected, not the task.
            if meta.get("turnContext"):
                continue
            text = _text_blocks(content)
            # A non-turnContext user text message starts a new eval turn.
            current = open_turn(agent_input=text)
            continue

        if role == "assistant":
            if not current:
                current = open_turn()
            pending_text: list = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "").strip()
                    if text:
                        pending_text.append(text)
                elif btype == "toolRequest":
                    call = (block.get("toolCall") or {}).get("value") or {}
                    step = {
                        "id": block.get("id"),
                        "tool": call.get("name"),
                        "tool_input_args": _tool_input_args(call.get("arguments")),
                        "tool_output": None,
                        "agent_thought": "\n".join(pending_text) or None,
                    }
                    pending_text = []
                    current["steps"].append(step)
                    if block.get("id"):
                        calls_by_id[block["id"]] = step
            # Text left after the last tool request (or a tool-less message) is the
            # agent's spoken response for this turn; keep the latest.
            if pending_text:
                current["agent_response"] = "\n".join(pending_text)
            usage = meta.get("usage")
            if isinstance(usage, dict):
                current["token_usage"] = usage

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
    workdir = tempfile.mkdtemp(prefix="goose-traj-")
    try:
        local_db = _copy_db(container_name, remote_path, workdir)
        if not local_db:
            print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
            return
        trajectory = parse_sessions_db(local_db)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps({"trajectory": trajectory}))


if __name__ == "__main__":
    main()
