#!/usr/bin/env python3
"""Post-run harvest for the grok-build harness.

The grok CLI persists the full session (every user query, assistant message,
tool call with its arguments, and tool result) to a per-session chat history at
``$HOME/.grok/sessions/<url-encoded-cwd>/<session-uuid>/chat_history.jsonl``.
Multi-turn conversations resume the SAME session (``grok -c``), so the newest
chat_history.jsonl holds the whole conversation.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the chat history out of the container and parse
it into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Token usage is NOT emitted here: grok's LLM traffic goes through the eval's /v1
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


def _read_chat_history(container_name: str) -> tuple:
    """Return (chat_history_text, session_id) from the container.

    Picks the newest chat_history.jsonl; session_id is its parent dir name
    (the grok session UUID). Returns ('', None) if none found.
    """
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.grok/sessions" -name "chat_history.jsonl" '
            r'-printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-',
        ],
        capture_output=True, text=True, check=False,
    )
    path = locate.stdout.strip()
    if not path:
        return "", None
    session_id = os.path.basename(os.path.dirname(path))
    dump = subprocess.run(
        [DOCKER, "exec", container_name, "cat", path],
        capture_output=True, text=True, check=False,
    )
    return dump.stdout, session_id


def _message_text(content) -> str:
    """grok message content is either a plain string or a list of typed segments."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for seg in content:
            if isinstance(seg, dict) and seg.get("type") == "text":
                parts.append(seg.get("text", ""))
            elif isinstance(seg, str):
                parts.append(seg)
        return "\n".join(p for p in parts if p).strip()
    return ""


def _strip_user_query(text: str) -> str:
    """The harness wraps each turn's task in <user_query>...</user_query>."""
    stripped = text.strip()
    if stripped.startswith("<user_query>") and stripped.endswith("</user_query>"):
        return stripped[len("<user_query>"):-len("</user_query>")].strip()
    return stripped


def _tool_input_args(arguments) -> list:
    """grok tool_call arguments is a JSON string of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def parse_chat_history(chat_text: str, session_id=None) -> dict:
    """Parse a grok chat_history.jsonl into the agent-inspect trace shape.

    Turns are delimited by ``user`` messages carrying a ``prompt_index`` (0, 1,
    ...); each is one real ``grok --single`` / ``grok -c`` invocation. The
    ``system`` message, the harness-injected ``<user_info>`` preamble, and
    ``synthetic_reason`` system reminders precede the first prompt_index and are
    not turn-opening. Assistant ``tool_calls`` and the matching ``tool_result``
    (by ``tool_call_id``) become steps; the final assistant text is the response.
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool_call_id -> step, for matching tool_result
    model_id = None

    def open_turn(turn_id=None) -> dict:
        turn = {
            "turn_id": turn_id,
            "agent_input": "",
            "agent_response": "",
            "steps": [],
            "token_usage": {},
        }
        turns.append(turn)
        return turn

    for line in chat_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")

        if mtype == "user":
            # Only a message bearing a prompt_index is a real task turn; the
            # <user_info> env preamble and synthetic_reason reminders are not.
            if msg.get("prompt_index") is not None:
                current = open_turn(msg.get("prompt_index"))
                current["agent_input"] = _strip_user_query(
                    _message_text(msg.get("content"))
                )
        elif mtype == "assistant":
            if model_id is None and msg.get("model_id"):
                model_id = msg.get("model_id")
            if not current:
                current = open_turn()
            for call in msg.get("tool_calls") or []:
                step = {
                    "id": call.get("id"),
                    "tool": call.get("name"),
                    "tool_input_args": _tool_input_args(call.get("arguments")),
                    "tool_output": None,
                    "agent_thought": None,
                }
                current["steps"].append(step)
                if call.get("id"):
                    calls_by_id[call["id"]] = step
            text = _message_text(msg.get("content"))
            if text:
                current["agent_response"] = text
        elif mtype == "tool_result":
            step = calls_by_id.get(msg.get("tool_call_id"))
            if step is not None:
                step["tool_output"] = _message_text(msg.get("content"))

    return {"turns": turns, "metadata": {"session_id": session_id, "model_id": model_id}}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    chat_text, session_id = _read_chat_history(container_name)
    if not chat_text:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_chat_history(chat_text, session_id)}))


if __name__ == "__main__":
    main()
