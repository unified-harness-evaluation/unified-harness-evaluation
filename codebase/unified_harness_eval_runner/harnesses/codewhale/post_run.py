#!/usr/bin/env python3
"""Post-run harvest for the codewhale harness.

codewhale persists the full session transcript to a single pretty-printed JSON
file per session at ``$HOME/.codewhale/sessions/<uuid>.json`` (HOME is /root in
this image). The relevant keys are:

* ``metadata`` -- session id, title, model, provider, workspace, cost.
* ``messages`` -- a flat, ordered list of conversation messages. Each message is
  ``{"role": "user"|"assistant", "content": [block, ...]}`` where a block is one
  of the Anthropic-style typed blocks:
    - ``text``        -- visible user task / assistant narration & final answer.
    - ``thinking`` / ``redacted_thinking`` -- model reasoning.
    - ``tool_use``    -- a tool call: ``{id, name, input{...}, execution_id}``.
    - ``tool_result`` -- the output of a prior tool_use, keyed by ``tool_use_id``.
  (``journal.entries`` carries the same messages as a parent-linked tree; we use
  the flat ``messages`` list.)

Multi-turn conversations resume the SAME session via ``--continue`` (resumes the
latest session), so every eval turn's messages are appended, in order, to that
one session file.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the newest top-level session JSON out of the
container and parse it into the agent-inspect trace shape, emitting it on stdout
as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the
eval's turns BY INDEX, and each eval turn is one ``codewhale ... exec`` /
``codewhale ... exec --continue`` invocation appended to the SAME session. Every
invocation injects a fresh user message whose first block is the real task text
(followed by a harness-injected ``<turn_meta>`` text block); tool_result user
messages carry no such task text. We therefore start a new turn at each user
message that contains real task text, so N invocations yield N turns in order.

Token usage is NOT emitted here: codewhale's LLM traffic goes through the eval's
/v1 proxy (metadata.total_tokens is 0 and no per-message usage is persisted), so
the gateway already attributes every token to this session.
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


def _read_session(container_name: str) -> str:
    """Return the newest top-level codewhale session JSON from the container.

    Session files are named ``<uuid>.json`` directly under
    ``$HOME/.codewhale/sessions``; we exclude the ``session_boot_owners.json``
    bookkeeping file and anything in nested dirs (e.g. ``.late-usage``). Returns
    '' when none is found."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.codewhale/sessions" -maxdepth 1 -type f -name "*.json" '
            '! -name "session_boot_owners.json" '
            r'-printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-',
        ],
        capture_output=True, text=True, check=False,
    )
    path = locate.stdout.strip()
    if not path:
        return ""
    dump = subprocess.run(
        [DOCKER, "exec", container_name, "cat", path],
        capture_output=True, text=True, check=False,
    )
    return dump.stdout


def _tool_input_args(arguments) -> list:
    """A codewhale tool_use ``input`` is a dict of named params."""
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


def _tool_result_text(block: dict):
    """Flatten a tool_result's content to text (or pass through structured)."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                parts.append(chunk.get("text", ""))
            elif isinstance(chunk, str):
                parts.append(chunk)
        if parts:
            return "\n".join(p for p in parts if p)
        return content
    return content


def _is_turn_meta(text: str) -> bool:
    """The harness appends a ``<turn_meta>`` scaffolding block to each real user
    task message; it is injected context, not the task."""
    return text.lstrip().startswith("<turn_meta>")


def parse_session(session_text: str) -> dict:
    """Parse a codewhale session JSON into the agent-inspect trace shape.

    A new turn opens at each user message that carries real task text (one
    ``codewhale ... exec`` invocation). tool_result user messages attach their
    outputs to the matching tool_use step in the current turn.
    """
    try:
        doc = json.loads(session_text)
    except (json.JSONDecodeError, ValueError):
        return {"turns": [], "metadata": {}}

    meta_in = doc.get("metadata") or {}
    metadata = {
        "session_id": meta_in.get("id"),
        "title": meta_in.get("title"),
        "model": meta_in.get("model"),
        "model_provider": meta_in.get("model_provider"),
        "workspace": meta_in.get("workspace"),
        "mode": meta_in.get("mode"),
    }

    messages = doc.get("messages") or []
    turns: list = []
    current: dict = {}
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

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        # codewhale always stores content as a list of typed blocks.
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue

        if role == "user":
            tool_results = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            task_text = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
                and b.get("text", "").strip() and not _is_turn_meta(b.get("text", ""))
            ).strip()

            if task_text:
                # A real task message starts a new eval turn.
                current = open_turn(agent_input=task_text)
            if tool_results:
                if not current:
                    current = open_turn()
                for tr in tool_results:
                    step = calls_by_id.get(tr.get("tool_use_id"))
                    if step is not None:
                        step["tool_output"] = _tool_result_text(tr)
            continue

        if role == "assistant":
            if not current:
                current = open_turn()
            pending_thought: str | None = None
            response_chunks: list = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    thought = (block.get("thinking") or "").strip()
                    if thought:
                        pending_thought = thought
                elif btype == "redacted_thinking":
                    pending_thought = "[redacted thinking]"
                elif btype == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        response_chunks.append(text)
                elif btype == "tool_use":
                    step = {
                        "id": block.get("id") or block.get("execution_id"),
                        "tool": block.get("name"),
                        "tool_input_args": _tool_input_args(block.get("input")),
                        "tool_output": None,
                        "agent_thought": pending_thought,
                    }
                    pending_thought = None
                    current["steps"].append(step)
                    if block.get("id"):
                        calls_by_id[block["id"]] = step
            if response_chunks:
                joined = "\n".join(response_chunks).strip()
                current["agent_response"] = (
                    (current["agent_response"] + "\n" + joined).strip()
                    if current["agent_response"]
                    else joined
                )
            continue

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    session_text = _read_session(container_name)
    if not session_text.strip():
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_session(session_text)}))


if __name__ == "__main__":
    main()
