#!/usr/bin/env python3
"""Post-run harvest for the opensquilla harness.

OpenSquilla persists the full session transcript to a SQLite database at
``$HOME/.opensquilla/state/sessions.db`` (HOME is /root in this image; the exact
path is pinned by this harness's ``session.flag`` ``--session-db-path``). The
conversation lives in the ``transcript_entries`` table, one row per message:

* ``role``             -- "user" / "assistant".
* ``content``          -- the message's flattened visible text.
* ``tool_calls``       -- for assistant rows, a JSON array of ordered,
  Anthropic-style typed blocks interleaving the step detail:
    - ``text``        -- assistant narration / final answer.
    - ``tool_use``    -- a tool call: ``{tool_use_id, name, input{...}}``.
    - ``tool_result`` -- that call's output: ``{tool_use_id, name, result,
      is_error}`` (results are stored INLINE in the same assistant row, not as a
      separate transcript entry).
* ``reasoning_content`` -- model reasoning for the message (may be null).
* ``turn_usage``       -- per-turn token/cost JSON for assistant rows.

Multi-turn conversations resume the SAME session db across invocations (this
harness pins ``--session-id eval-session --session-db-path .../sessions.db``,
``always: true``), so every eval turn appends a fresh user row + assistant row,
in order, to that one transcript.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we dump the transcript (and the session row) out of the
container with a tiny python3 reader -- the image ships python3 whose stdlib
``sqlite3`` reads the live DB including any uncheckpointed WAL -- and parse it
into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the
eval's turns BY INDEX, and each eval turn is one ``opensquilla agent`` invocation
appended to the SAME session db. Each invocation writes one user row (the real
task) followed by its assistant row(s); we therefore start a new turn at every
user row, so N invocations yield N turns in order.
"""
import json
import os
import re
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

# python3 program (run inside the container with `python3 -`) that reads
# opensquilla's SQLite transcript and dumps the session row + ordered transcript
# entries as a single JSON object. Opening the live DB picks up WAL-resident rows.
_DUMP_SCRIPT = r"""
import json, os, sqlite3, sys
candidates = [
    os.path.join(os.environ.get("HOME", "/root"), ".opensquilla/state/sessions.db"),
    "/root/.opensquilla/state/sessions.db",
]
db_path = next((p for p in candidates if os.path.isfile(p)), None)
if not db_path:
    sys.stdout.write("null"); sys.exit(0)
conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
conn.row_factory = sqlite3.Row
def rows(sql):
    try:
        return [dict(r) for r in conn.execute(sql)]
    except sqlite3.Error:
        return []
session = None
srows = rows("SELECT * FROM sessions ORDER BY updated_at DESC, created_at DESC LIMIT 1")
if srows:
    session = srows[0]
entries = rows(
    "SELECT id, role, content, tool_calls, tool_call_id, reasoning_content, "
    "turn_usage, created_at FROM transcript_entries ORDER BY created_at, id"
)
sys.stdout.write(json.dumps({"session": session, "entries": entries}))
"""

_TS_PREFIX = re.compile(r"^\s*\[[^\]\n]*\]\s*\n")


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
    """Dump opensquilla's SQLite transcript out of the container as a dict.

    Returns None when no DB / no data is found."""
    proc = subprocess.run(
        [DOCKER, "exec", "-i", container_name, "python3", "-"],
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


def _strip_task(text: str) -> str:
    """Drop the leading ``[timestamp ...]`` line the runtime prepends to the user
    task before storing it, leaving the real prompt."""
    if not isinstance(text, str):
        return ""
    return _TS_PREFIX.sub("", text, count=1).strip()


def _tool_input_args(arguments) -> list:
    """An opensquilla tool_use ``input`` is a dict of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "input", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    if arguments is None:
        return []
    return [{"name": "input", "value": arguments}]


def _tool_result_value(block: dict):
    """A tool_result stores its output in ``result`` (usually a string)."""
    result = block.get("result")
    if result is None:
        result = block.get("content")
    return result


def _token_usage(raw) -> dict:
    """Map opensquilla's ``turn_usage`` JSON onto the trace token fields."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    inp = raw.get("input_tokens") or 0
    out = raw.get("output_tokens") or 0
    rea = raw.get("reasoning_tokens") or 0
    return {
        "input": inp,
        "output": out,
        "reasoning": rea,
        "cache_read": raw.get("cached_tokens") or 0,
        "cache_write": raw.get("cache_write_tokens") or 0,
        "total": inp + out + rea,
    }


def _blocks_of(entry: dict) -> list:
    """Return an assistant row's ordered typed blocks from ``tool_calls`` (which
    holds the full interleaved text/tool_use/tool_result list), falling back to a
    single text block from ``content``."""
    raw = entry.get("tool_calls")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = None
    if isinstance(raw, list) and raw:
        return raw
    text = entry.get("content")
    if isinstance(text, str) and text.strip():
        return [{"type": "text", "text": text}]
    return []


def parse_db(dump: dict) -> dict:
    """Parse the dumped opensquilla transcript into the agent-inspect trace shape.

    A new turn opens at each user row (one ``opensquilla agent`` invocation); the
    assistant row(s) that follow attach their steps, response and tokens to it.
    tool_result blocks are matched to their tool_use step by ``tool_use_id``.
    """
    session = dump.get("session") or {}
    entries = dump.get("entries") or []

    turns: list = []
    current: dict | None = None
    calls_by_id: dict = {}  # tool_use_id -> step, scoped to the current turn

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

    for entry in entries:
        role = entry.get("role")

        if role == "user":
            current = open_turn(agent_input=_strip_task(entry.get("content")))
            current["turn_id"] = entry.get("message_id") if "message_id" in entry else None
            continue

        if role != "assistant":
            # Defensive: a standalone tool row would carry results for the current
            # turn's open calls.
            if role == "tool" and current is not None:
                for block in _blocks_of(entry):
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        step = calls_by_id.get(block.get("tool_use_id"))
                        if step is not None:
                            step["tool_output"] = _tool_result_value(block)
            continue

        if current is None:
            current = open_turn()

        pending_thought = (entry.get("reasoning_content") or "").strip() or None
        response_chunks: list = []
        for block in _blocks_of(entry):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype in ("thinking", "reasoning"):
                thought = (block.get("thinking") or block.get("text") or "").strip()
                if thought:
                    pending_thought = thought
            elif btype == "text":
                text = (block.get("text") or "").strip()
                if text:
                    response_chunks.append(text)
            elif btype == "tool_use":
                step = {
                    "id": block.get("tool_use_id") or block.get("id"),
                    "tool": block.get("name"),
                    "tool_input_args": _tool_input_args(block.get("input")),
                    "tool_output": None,
                    "agent_thought": pending_thought,
                }
                pending_thought = None
                current["steps"].append(step)
                key = block.get("tool_use_id") or block.get("id")
                if key:
                    calls_by_id[key] = step
            elif btype == "tool_result":
                step = calls_by_id.get(block.get("tool_use_id"))
                if step is not None:
                    step["tool_output"] = _tool_result_value(block)

        if response_chunks:
            joined = "\n".join(response_chunks).strip()
            current["agent_response"] = (
                (current["agent_response"] + "\n" + joined).strip()
                if current["agent_response"]
                else joined
            )
        usage = _token_usage(entry.get("turn_usage"))
        if usage:
            current["token_usage"] = usage

    metadata = {}
    if isinstance(session, dict) and session:
        metadata = {
            "session_id": session.get("session_id"),
            "session_key": session.get("session_key"),
            "model": session.get("model"),
            "model_provider": session.get("model_provider"),
            "total_tokens": session.get("total_tokens"),
            "total_cost_usd": session.get("total_cost_usd"),
            "agent_id": session.get("agent_id"),
        }
    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    dump = _read_db(container_name)
    if not dump or not dump.get("entries"):
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_db(dump)}))


if __name__ == "__main__":
    main()
