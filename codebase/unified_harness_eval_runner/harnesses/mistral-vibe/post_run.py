#!/usr/bin/env python3
"""Post-run harvest for the mistral-vibe harness.

Vibe persists every session under
``$HOME/.vibe/logs/session/unified/<session-id>/``. Each session keeps an
event journal plus periodic checkpoints ("generations"). The LATEST generation's
``manifest.json`` points at the content-addressed ``chunks/<sha>.json`` that holds
the materialised projection: the full, ordered conversation across EVERY turn
(user messages, assistant replies, and tool "effect" entries with their inputs
and outputs). Multi-turn runs resume the SAME session (``vibe -c``), so the newest
session's newest generation holds the whole conversation; each entry carries a
``turnId`` that delimits the eval turns.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the projection chunk out of the container and
parse it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Token usage is NOT emitted here: vibe's LLM traffic goes through the eval's /v1
proxy, so the gateway already attributes every token to this session.
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

# Resolves (inside the container) the newest vibe session, its newest checkpoint
# generation, and the projection chunk(s) that generation points at. Prints a
# single JSON object {"entries": [...], "metadata": {...}} on stdout. Kept
# in-container because the chunk is content-addressed: only the manifest knows
# which sha holds the materialised conversation.
_RESOLVER = r'''
import json, os, glob
base = os.path.expanduser("~/.vibe/logs/session/unified")
sessions = [d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(d)]
if not sessions:
    print(json.dumps({"entries": [], "metadata": {}}))
    raise SystemExit
# Newest session: vibe -c resumes the same session, so the most recently touched
# session dir holds the whole conversation.
sess = max(sessions, key=os.path.getmtime)
meta = {}
try:
    m = json.load(open(os.path.join(sess, "meta.json")))
    meta["session_id"] = m.get("session_id")
    meta["cwd"] = (m.get("environment") or {}).get("working_directory") or m.get("origin_directory")
except Exception:
    pass
try:
    idx = json.load(open(os.path.join(base, ".session-index.json")))
    for ent in idx.get("entries") or []:
        if (ent.get("session") or {}).get("id") == os.path.basename(sess):
            meta["model"] = (ent.get("metadata") or {}).get("active_model")
            break
except Exception:
    pass
entries = []
gens = sorted(glob.glob(os.path.join(sess, "generations", "*")))
if gens:
    latest = gens[-1]
    try:
        manifest = json.load(open(os.path.join(latest, "manifest.json")))
        for h in (manifest.get("projection_state") or {}).get("chunks") or []:
            cp = os.path.join(sess, "chunks", h + ".json")
            if os.path.exists(cp):
                part = json.load(open(cp))
                if isinstance(part, list):
                    entries.extend(part)
    except Exception:
        pass
print(json.dumps({"entries": entries, "metadata": meta}))
'''


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


def _read_projection(container_name: str) -> dict:
    """Return {"entries": [...], "metadata": {...}} from the container, or {}."""
    proc = subprocess.run(
        [DOCKER, "exec", container_name, "python3", "-c", _RESOLVER],
        capture_output=True, text=True, check=False,
    )
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {}


def _message_text(content) -> str:
    """Join the text segments of a projection message entry's content."""
    parts = []
    for chunk in content or []:
        if isinstance(chunk, dict) and chunk.get("type") == "text":
            parts.append(chunk.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _tool_input_args(inp) -> list:
    """A tool effect's ``detail.input`` is a dict of named params."""
    if isinstance(inp, dict):
        return [{"name": name, "value": value} for name, value in inp.items()]
    if inp is None:
        return []
    return [{"name": "input", "value": inp}]


def _tool_output(state: dict):
    """Prefer the structured tool result; fall back to text/raw output."""
    state = state or {}
    out = state.get("output")
    if isinstance(out, dict):
        sc = out.get("structured_content")
        if sc not in (None, {}, []):
            return sc
    text = state.get("outputText")
    if text:
        return text
    return out


def parse_entries(entries: list, metadata: dict) -> dict:
    """Parse vibe projection entries into the agent-inspect trace shape.

    Entries are the full ordered conversation. Turns are delimited by ``turnId``
    (one per ``vibe`` invocation / eval turn); grouping by first-seen turnId
    preserves chronological turn order, matching the eval's turn structure.
    """
    turns: list = []
    by_turn: dict = {}

    def turn_for(turn_id):
        if turn_id not in by_turn:
            turn = {
                "turn_id": turn_id,
                "agent_input": "",
                "agent_response": "",
                "steps": [],
                "token_usage": {},
            }
            by_turn[turn_id] = turn
            turns.append(turn)
        return by_turn[turn_id]

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        turn = turn_for(entry.get("turnId"))
        entry_type = entry.get("type")

        if entry_type == "message":
            text = _message_text(entry.get("content"))
            if not text:
                continue
            role = entry.get("role")
            # source == turn_start is the real user utterance for this turn;
            # other user entries are harness-injected scaffolding.
            if role == "user" and entry.get("source") == "turn_start":
                turn["agent_input"] = (
                    f"{turn['agent_input']}\n{text}".strip()
                    if turn["agent_input"] else text
                )
            elif role == "assistant":
                turn["agent_response"] = (
                    f"{turn['agent_response']}\n{text}".strip()
                    if turn["agent_response"] else text
                )
        elif entry_type == "effect":
            detail = entry.get("detail") or {}
            tool = detail.get("toolName")
            if not tool:
                continue
            turn["steps"].append({
                "id": entry.get("id"),
                "tool": tool,
                "tool_input_args": _tool_input_args(detail.get("input")),
                "tool_output": _tool_output(entry.get("state")),
                "agent_thought": None,
            })

    return {"turns": turns, "metadata": metadata or {}}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    projection = _read_projection(container_name)
    entries = projection.get("entries") or []
    metadata = projection.get("metadata") or {}
    print(json.dumps({"trajectory": parse_entries(entries, metadata)}))


if __name__ == "__main__":
    main()
