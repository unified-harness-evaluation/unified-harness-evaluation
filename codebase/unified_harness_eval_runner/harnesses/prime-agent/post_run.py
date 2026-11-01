#!/usr/bin/env python3
"""Post-run harvest for the prime-agent harness.

Prime Intellect's ``prime-agent`` persists the full session transcript -- every
user/assistant message, tool call, tool result and per-inference token usage --
as an append-only JSONL event log at::

    $HOME/.prime/agent/sessions/<uuid>.jsonl

(HOME is ``/root`` in this image.) Each line is one event object. Multi-turn
conversations resume the SAME session (``prime-agent -c`` / ``--continue``
appends more events to this one file), so the newest session file holds the
whole conversation.

Event schema (fields abbreviated):

* ``session``       -- header: id, cwd, version, git (metadata).
* ``model_change``  -- ``{provider, modelId}``; the selected model (metadata).
* ``custom_message``-- harness scaffolding (e.g. ``harness_digest``); skipped.
* ``message`` with ``message.role``:
    - ``user``       -- ``content:[{type:"text",text}]``; the real task prompt.
      Each user message is one CLI invocation, i.e. one eval turn.
    - ``assistant``  -- ``content:[{type:"toolCall",id,name,arguments{...}} |
      {type:"text",text} | {type:"thinking",...}]`` plus ``usage``. Text/thinking
      preceding a toolCall is that step's thought; a toolCall-less text message is
      the turn's spoken response.
    - ``toolResult`` -- ``{toolCallId, toolName, content:[{type:text,text}],
      isError}``; matched to its call by ``toolCallId``.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the newest session JSONL out of the container and
parse it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the eval's
turns BY INDEX, and each eval turn is one ``prime-agent`` / ``prime-agent -c``
(resume) invocation appended to the SAME session. We open a new turn at each
``message`` whose role is ``user``, in order, so N invocations yield N turns.
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
    """Return the newest prime-agent session JSONL from the container, or ''."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.prime/agent/sessions" -type f -name "*.jsonl" '
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


def _message_text(content) -> str:
    """Join the text segments of a message's content array."""
    parts = []
    for chunk in content or []:
        if isinstance(chunk, dict) and chunk.get("type") == "text":
            parts.append(chunk.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _tool_input_args(arguments) -> list:
    """A prime-agent toolCall's arguments is a dict of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    if arguments is None:
        return []
    return [{"name": "arguments", "value": arguments}]


def _tool_result_output(message: dict):
    """Flatten a toolResult message's content to text (fallback to details)."""
    text = _message_text(message.get("content"))
    if text:
        return text
    details = message.get("details")
    if isinstance(details, dict) and details.get("result") is not None:
        return details.get("result")
    return None


def _accumulate_tokens(acc: dict, usage: dict) -> None:
    """Fold an assistant message's usage into the turn accumulator."""
    if not isinstance(usage, dict):
        return
    acc["input"] += usage.get("input") or 0
    acc["output"] += usage.get("output") or 0
    acc["cache_read"] += usage.get("cacheRead") or 0
    acc["cache_write"] += usage.get("cacheWrite") or 0
    acc["total"] += usage.get("totalTokens") or 0


def parse_session(session_text: str) -> dict:
    """Parse a prime-agent session JSONL into the agent-inspect trace shape.

    A new turn opens at each ``message`` with role ``user`` (one CLI
    invocation). Within a turn, assistant ``toolCall`` blocks become steps (text
    preceding a toolCall is its thought), ``toolResult`` messages fill in each
    step's output by ``toolCallId``, and a toolCall-less assistant text message
    is the turn's spoken response.
    """
    turns: list = []
    current: dict | None = None
    calls_by_id: dict = {}  # toolCallId -> step, scoped to the current turn
    metadata: dict = {}

    def open_turn(agent_input="") -> dict:
        nonlocal calls_by_id
        turn = {
            "turn_id": None,
            "agent_input": agent_input,
            "agent_response": "",
            "steps": [],
            "token_usage": {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "total": 0,
            },
        }
        turns.append(turn)
        calls_by_id = {}
        return turn

    for line in session_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        etype = event.get("type")

        if etype == "session":
            metadata.update({
                "session_id": event.get("id"),
                "cwd": event.get("cwd"),
                "version": event.get("version"),
            })
            continue
        if etype == "model_change":
            metadata["provider"] = event.get("provider")
            metadata["model"] = event.get("modelId")
            continue
        if etype != "message":
            continue

        message = event.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")

        if role == "user":
            # Each user message is one CLI invocation -> a new eval turn.
            current = open_turn(agent_input=_message_text(message.get("content")))
            continue

        if role == "toolResult":
            if current is None:
                continue
            step = calls_by_id.get(message.get("toolCallId"))
            if step is not None:
                step["tool_output"] = _tool_result_output(message)
            continue

        if role == "assistant":
            if current is None:
                current = open_turn()
            pending_text: list = []
            had_tool_call = False
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        pending_text.append(text)
                elif btype in ("thinking", "redacted_thinking", "reasoning"):
                    thought = (
                        block.get("thinking") or block.get("text") or ""
                    ).strip()
                    if thought:
                        pending_text.append(thought)
                elif btype == "toolCall":
                    had_tool_call = True
                    step = {
                        "id": block.get("id"),
                        "tool": block.get("name"),
                        "tool_input_args": _tool_input_args(block.get("arguments")),
                        "tool_output": None,
                        "agent_thought": "\n".join(pending_text) or None,
                    }
                    pending_text = []
                    current["steps"].append(step)
                    if block.get("id"):
                        calls_by_id[block["id"]] = step
            # Text in a toolCall-less message is the turn's spoken answer; keep
            # the latest such message.
            if pending_text and not had_tool_call:
                current["agent_response"] = "\n".join(pending_text)
            _accumulate_tokens(current["token_usage"], message.get("usage"))
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
