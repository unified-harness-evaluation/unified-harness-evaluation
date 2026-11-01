#!/usr/bin/env python3
"""Post-run harvest for the deepseek-reasonix harness.

Reasonix persists the full conversation as a flat message log at
``$HOME/.reasonix/projects/<slug>/sessions/<timestamp>-<model>.jsonl``. Each line
is one message: ``system`` (prompt scaffolding), ``user`` (carries the clean task
in ``raw_content``), ``assistant`` (either ``tool_calls`` or a final ``content``),
and ``tool`` (the tool result, linked back by ``tool_call_id``). Multi-turn
conversations resume the SAME session file (``reasonix -c``), appending; every
eval turn begins with a fresh ``user`` message that has ``raw_content``, so those
delimit the turns one-to-one with the CLI invocations.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the newest session log out of the container and
parse it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Reasonix is a reasoning-model CLI: when the model emits reasoning/thinking text it
is mapped onto the owning step's ``agent_thought``. (In practice the persisted
transcript schema records reasoning only as a token count, not text; the fields
below are harvested defensively for models/versions that do persist the text.)

Token usage is NOT emitted here: reasonix's LLM traffic goes through the eval's
/v1 proxy, so the gateway already attributes every token to this session.
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

# Keys a reasoning-model transcript might use for persisted thinking text.
_THOUGHT_KEYS = ("reasoning_content", "reasoning", "thinking", "thought")


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
    """Return the newest reasonix session transcript JSONL, or '' if none.

    The main transcript is ``<name>.jsonl``; sidecars (``<name>.events.jsonl``,
    ``<name>.jsonl.telemetry.json``, ``*.lease.json``, ``*.recovery.json`` ...)
    are excluded so we parse the clean message log.
    """
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.reasonix/projects" -type f -name "*.jsonl" '
            '! -name "*.events.jsonl" '
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
    """Reasonix tool-call arguments is a JSON string of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def _thought_text(message: dict) -> str:
    """Pull any persisted reasoning/thinking text off an assistant message."""
    for key in _THOUGHT_KEYS:
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            joined = "\n".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in value
            ).strip()
            if joined:
                return joined
    return ""


def parse_session(session_text: str) -> dict:
    """Parse a reasonix session JSONL into the agent-inspect trace shape.

    Turns are delimited by ``user`` messages carrying ``raw_content`` (each is one
    ``reasonix`` / ``reasonix -c`` invocation = one eval turn). Assistant
    ``tool_calls`` become steps; the following ``tool`` message fills the step's
    output; a tool-less assistant ``content`` is the turn's final response.
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool_call_id -> step, for matching tool results

    def open_turn(agent_input="") -> dict:
        turn = {
            "turn_id": str(len(turns)),
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
            message = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(message, dict):
            continue
        role = message.get("role")

        if role == "system":
            continue  # harness-injected prompt scaffolding, not a turn
        if role == "user":
            # Every eval turn starts with a fresh user message; raw_content is the
            # clean task (content is the harness-wrapped prompt).
            agent_input = message.get("raw_content") or message.get("content") or ""
            current = open_turn(agent_input)
        elif role == "assistant":
            if not current:
                current = open_turn()
            thought = _thought_text(message)
            tool_calls = message.get("tool_calls") or []
            for call in tool_calls:
                step = {
                    "id": call.get("id"),
                    "tool": call.get("name"),
                    "tool_input_args": _tool_input_args(call.get("arguments")),
                    "tool_output": None,
                    "agent_thought": thought or None,
                }
                current["steps"].append(step)
                if call.get("id"):
                    calls_by_id[call["id"]] = step
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                if tool_calls:
                    # preamble text alongside tool calls -> reasoning on first step
                    if not current["steps"][-len(tool_calls)].get("agent_thought"):
                        current["steps"][-len(tool_calls)]["agent_thought"] = content.strip()
                else:
                    current["agent_response"] = content.strip()
        elif role == "tool":
            step = calls_by_id.get(message.get("tool_call_id"))
            if step is not None:
                step["tool_output"] = message.get("content")

    return {"turns": turns, "metadata": {}}


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
