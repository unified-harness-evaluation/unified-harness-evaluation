#!/usr/bin/env python3
"""Post-run harvest for the jcode harness.

jcode persists the full session transcript (every user/assistant message, tool
call, tool result and per-assistant-message token usage) as a single JSON file at
``$HOME/.jcode/sessions/session_*.json`` (HOME is /root in this image). The file
holds a top-level ``messages`` array in Anthropic message shape: each message has
a ``role`` ("user" / "assistant") and a ``content`` list of typed blocks --
``text`` (visible user task / assistant reply), ``tool_use`` (a tool call with
named ``input`` params) and ``tool_result`` (the output of a tool_use, carried in
a following *user* message keyed by ``tool_use_id``). Multi-turn conversations
resume the SAME session (``jcode run ... --resume {session_id}``), so every eval
turn's messages are appended, in order, to that one file.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the newest session JSON out of the container and
parse it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the eval's
turns BY INDEX, where each eval turn is one ``jcode run`` invocation. Each
invocation injects the task as a *user* ``text`` message; we start a new turn at
every such real user message, skipping the harness-injected ``<system-reminder>``
scaffolding (``display_role: system``) and ``tool_result`` carrier messages, so N
invocations yield N turns in order.
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
    """Return the newest jcode session JSON from the container, or '' if none.

    We restrict to the top level of the sessions dir (``-maxdepth 1``) so we never
    pick up the ``edit-stats/`` sidecar files that share the session filename, and
    we match only ``session_*.json`` to skip ``.bak`` snapshots."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.jcode/sessions" -maxdepth 1 -type f -name "session_*.json" '
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


def _tool_input_args(args) -> list:
    """A jcode tool_use block's ``input`` is a dict of named params."""
    if isinstance(args, dict):
        return [{"name": name, "value": value} for name, value in args.items()]
    if args is None:
        return []
    return [{"name": "input", "value": args}]


def _text_of(content) -> str:
    """Join the ``text`` blocks of a message's content list."""
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _is_system_reminder(message: dict) -> bool:
    """The harness injects a ``<system-reminder>`` user message (session context,
    OS/git state) before the real task; it is scaffolding, not a turn prompt."""
    if message.get("display_role") == "system":
        return True
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            if block.get("text", "").lstrip().startswith("<system-reminder>"):
                return True
    return False


def _tool_result_output(block: dict):
    """A tool_result block's ``content`` is the tool output (usually a string)."""
    return block.get("content")


def _accumulate_tokens(acc: dict, tokens: dict) -> None:
    """Fold a per-assistant-message token_usage dict into the turn accumulator."""
    if not isinstance(tokens, dict):
        return
    acc["input"] += tokens.get("input_tokens") or tokens.get("prompt_tokens") or 0
    acc["output"] += tokens.get("output_tokens") or 0
    acc["cache_read"] += tokens.get("cache_read_input_tokens") or 0
    acc["cache_write"] += tokens.get("cache_creation_input_tokens") or 0


def parse_session(session_text: str) -> dict:
    """Parse a jcode session JSON into the agent-inspect trace shape.

    We walk ``messages`` in order. A new turn opens at each real user *text*
    message (the task handed to one ``jcode run`` invocation); ``<system-reminder>``
    scaffolding and ``tool_result`` carrier messages attach to / are consumed by
    the current turn instead. Assistant ``tool_use`` blocks become steps whose
    output is filled in from the matching ``tool_result`` (by ``tool_use_id``);
    assistant ``text`` is the spoken response (``thinking`` precedes a step as its
    thought).
    """
    try:
        session = json.loads(session_text)
    except (json.JSONDecodeError, ValueError):
        return {"turns": [], "metadata": {}}
    if not isinstance(session, dict):
        return {"turns": [], "metadata": {}}

    messages = session.get("messages") or []

    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool_use_id -> step, for matching tool_result

    def open_turn(agent_input="", turn_id=None) -> dict:
        nonlocal calls_by_id
        turn = {
            "turn_id": turn_id,
            "agent_input": agent_input,
            "agent_response": "",
            "steps": [],
            "token_usage": {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
            },
        }
        turns.append(turn)
        calls_by_id = {}
        return turn

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content") or []

        if role == "user":
            tool_results = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            if tool_results:
                for tr in tool_results:
                    step = calls_by_id.get(tr.get("tool_use_id"))
                    if step is not None:
                        step["tool_output"] = _tool_result_output(tr)
                continue
            # <system-reminder> scaffolding is harness-injected, not the task.
            if _is_system_reminder(message):
                continue
            text = _text_of(content)
            # A real user text message starts a new eval turn.
            current = open_turn(agent_input=text, turn_id=message.get("id"))
            continue

        if role != "assistant":
            continue
        if not current:
            current = open_turn()

        pending_thought: list = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "thinking":
                thought = (block.get("thinking") or block.get("text") or "").strip()
                if thought:
                    pending_thought.append(thought)
            elif btype == "text":
                text = block.get("text", "").strip()
                if text:
                    current["agent_response"] = (
                        (current["agent_response"] + "\n" + text).strip()
                        if current["agent_response"]
                        else text
                    )
            elif btype == "tool_use":
                current["steps"].append({
                    "id": block.get("id"),
                    "tool": block.get("name"),
                    "tool_input_args": _tool_input_args(block.get("input")),
                    "tool_output": None,
                    "agent_thought": "\n".join(pending_thought) or None,
                })
                pending_thought = []
                if block.get("id"):
                    calls_by_id[block["id"]] = current["steps"][-1]
        _accumulate_tokens(current["token_usage"], message.get("token_usage") or {})

    for turn in turns:
        tu = turn["token_usage"]
        tu["total"] = tu["input"] + tu["output"]

    metadata = {
        "session_id": session.get("id"),
        "title": session.get("title"),
        "model": session.get("model"),
        "provider": session.get("provider_key"),
        "working_dir": session.get("working_dir"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }
    snapshots = session.get("env_snapshots") or []
    if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict):
        metadata["cli_version"] = snapshots[0].get("jcode_version")
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
