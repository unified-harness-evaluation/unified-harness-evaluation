#!/usr/bin/env python3
"""Post-run harvest for the oh-my-pi harness.

The ``omp`` CLI (``@oh-my-pi/pi-coding-agent``) is a fork of pi and shares its
session format: a conversation is persisted as a JSONL file under
``$HOME/.omp/agent/sessions/--<cwd>--/<timestamp>_<session-id>.jsonl``. Each line
is one session entry with a ``type`` field; the conversation itself is a stream
of ``message`` entries whose ``message.role`` is user / assistant / toolResult.
Assistant messages carry the content blocks (``text`` / ``thinking`` /
``toolCall``) and per-call ``usage``; tool outputs arrive as separate
``toolResult`` entries keyed by ``toolCallId``. Non-message bookkeeping entries
(``title`` / ``session`` / ``model_change`` / ``thinking_level_change`` /
top-level ``custom`` scaffolding) are skipped.

Multi-turn conversations resume the SAME session (``omp -c`` opens the most
recent session for the cwd and appends), so the newest session file holds the
whole conversation. Each eval turn is one ``omp -p`` invocation, which appends a
fresh ``user`` message; we therefore delimit turns on ``user`` messages.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the session file out of the container and parse
it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Token usage is best-effort: omp's LLM traffic goes through the eval's proxy, so
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
    """Return the newest omp session JSONL from the container, or '' if none.

    omp stores sessions under ``$HOME/.omp/agent/sessions`` by default. The
    newest file holds the full conversation because ``omp -c`` appends.
    """
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.omp/agent/sessions" -name "*.jsonl" '
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


def _content_text(content) -> str:
    """Join the text blocks of a message content (string or block list)."""
    if isinstance(content, str):
        return content.strip()
    parts = []
    for chunk in content or []:
        if isinstance(chunk, dict) and chunk.get("type") == "text":
            parts.append(chunk.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _thinking_text(content) -> str:
    """Join the thinking blocks of an assistant message content list."""
    if not isinstance(content, list):
        return ""
    parts = []
    for chunk in content or []:
        if isinstance(chunk, dict) and chunk.get("type") == "thinking":
            parts.append(chunk.get("thinking", ""))
    return "\n".join(p for p in parts if p).strip()


def _tool_input_args(arguments) -> list:
    """omp toolCall.arguments is already a dict of named params."""
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
        if isinstance(parsed, dict):
            return [{"name": n, "value": v} for n, v in parsed.items()]
    return [{"name": "arguments", "value": arguments}]


def _aggregate_usage(acc: dict, usage: dict) -> None:
    """Fold a per-call Usage into the turn's accumulator in place.

    ``input`` / ``cacheRead`` are cumulative context (each call re-sends prior
    turn history) so we keep the max; generation fields are summed. The result
    is a rough per-turn figure -- it is not the field the merge consumes (the
    gateway proxy already attributes tokens), so approximation is acceptable.
    """
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if key == "cost" and isinstance(value, dict):
            cost = acc.setdefault("cost", {})
            for ck, cv in value.items():
                if isinstance(cv, (int, float)):
                    cost[ck] = cost.get(ck, 0) + cv
        elif isinstance(value, (int, float)):
            if key in ("input", "cacheRead"):
                acc[key] = max(acc.get(key, 0), value)
            else:
                acc[key] = acc.get(key, 0) + value


def parse_session(session_text: str) -> dict:
    """Parse an omp session JSONL into the agent-inspect trace shape.

    The file is an append-ordered entry stream; in non-interactive eval runs
    there is no tree branching, so file order == the linear conversation. Turns
    are delimited by ``user`` messages (one per ``omp -p`` invocation).
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # toolCallId -> step, for matching toolResult
    metadata: dict = {}

    def open_turn(agent_input="") -> dict:
        turn = {
            "turn_id": None,
            "agent_input": agent_input,
            "agent_response": "",
            "steps": [],
            "token_usage": {},
        }
        turns.append(turn)
        return turn

    for line in session_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        entry_type = entry.get("type")

        if entry_type == "session":
            metadata.update({
                "session_id": entry.get("id"),
                "cwd": entry.get("cwd"),
                "version": entry.get("version"),
            })
            continue
        if entry_type == "model_change":
            # omp records a single "openai/claude-opus-4-6" string; pi split it
            # into provider/modelId. Capture whatever is present.
            if entry.get("model") is not None:
                metadata["model"] = entry.get("model")
            if entry.get("provider") is not None:
                metadata["model_provider"] = entry.get("provider")
            if entry.get("modelId") is not None:
                metadata["model_id"] = entry.get("modelId")
            continue
        if entry_type == "usage":
            # Non-message model work (e.g. cache warming) attributed to the turn.
            if current:
                _aggregate_usage(current["token_usage"], entry.get("usage") or {})
            continue
        if entry_type != "message":
            continue

        message = entry.get("message") or {}
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            continue  # prompt/tool scaffolding, not conversation
        elif role == "user" or role == "custom":
            text = _content_text(content)
            # A user message starts a new eval turn / CLI invocation.
            current = open_turn(agent_input=text)
            current["turn_id"] = entry.get("id")
        elif role == "assistant":
            if not current:
                current = open_turn()
            thought = _thinking_text(content)
            text = _content_text(content)
            if text:
                current["agent_response"] = (
                    (current["agent_response"] + "\n" + text).strip()
                    if current["agent_response"] else text
                )
            made_step = False
            for block in content or []:
                if not isinstance(block, dict) or block.get("type") != "toolCall":
                    continue
                step = {
                    "id": block.get("id"),
                    "tool": block.get("name"),
                    "tool_input_args": _tool_input_args(block.get("arguments")),
                    "tool_output": None,
                    "agent_thought": thought or None,
                }
                current["steps"].append(step)
                made_step = True
                if block.get("id"):
                    calls_by_id[block["id"]] = step
            # Reasoning on a final (text-only) assistant message has no step to
            # attach to; hang it on the turn's last step if one exists.
            if thought and not made_step and current["steps"]:
                if not current["steps"][-1]["agent_thought"]:
                    current["steps"][-1]["agent_thought"] = thought
            _aggregate_usage(current["token_usage"], message.get("usage") or {})
        elif role == "toolResult":
            step = calls_by_id.get(message.get("toolCallId"))
            if step is not None:
                output = _content_text(content)
                if message.get("isError"):
                    output = "[error] " + output
                step["tool_output"] = output
                _aggregate_usage(current["token_usage"], message.get("usage") or {})
        elif role == "bashExecution":
            # Direct shell command (RPC bash); not an LLM tool result.
            if not current:
                current = open_turn()
            current["steps"].append({
                "id": entry.get("id"),
                "tool": "bash",
                "tool_input_args": [{"name": "command", "value": message.get("command")}],
                "tool_output": message.get("output"),
                "agent_thought": None,
            })

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    session_text = _read_session(container_name)
    if not session_text:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_session(session_text)}))


if __name__ == "__main__":
    main()
