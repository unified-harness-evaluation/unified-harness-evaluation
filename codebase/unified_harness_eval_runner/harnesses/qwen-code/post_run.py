#!/usr/bin/env python3
"""Post-run harvest for the qwen-code harness.

qwen-code (a Qwen/Gemini-CLI-family tool) streams the full session (every user
prompt, assistant message, function call, tool result and thinking part) to a
chat JSONL at
``$HOME/.qwen/projects/<project>/chats/<session-uuid>.jsonl``.
Multi-turn conversations resume the SAME chat file (the harness continues the
session via ``qwen -c``), so the newest chat JSONL holds the whole conversation.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the chat JSONL out of the container and parse it
into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Token usage is NOT emitted here: qwen's LLM traffic goes through the eval's /v1
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


def _read_chat(container_name: str) -> str:
    """Return the newest qwen chat JSONL from the container, or '' if none."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.qwen/projects" -path "*/chats/*.jsonl" '
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


def _text_parts(parts: list) -> str:
    """Join the non-thought text segments of a message's parts."""
    out = []
    for part in parts:
        if isinstance(part, dict) and "text" in part and not part.get("thought"):
            out.append(part.get("text") or "")
    return "\n".join(p for p in out if p).strip()


def _thought_text(parts: list) -> str:
    """Join the thinking/thought text segments of a message's parts."""
    out = []
    for part in parts:
        if isinstance(part, dict) and part.get("thought") and part.get("text"):
            out.append(part["text"])
    return "\n".join(out).strip()


def _tool_input_args(args) -> list:
    """qwen function-call args is an object of named params."""
    if isinstance(args, dict):
        return [{"name": name, "value": value} for name, value in args.items()]
    return [{"name": "args", "value": args}]


def _tool_output(response):
    """Extract the readable payload from a functionResponse.response."""
    if isinstance(response, dict):
        if "output" in response:
            return response["output"]
        if "error" in response:
            return {"error": response["error"]}
        return response
    return response


def parse_chat(chat_text: str) -> dict:
    """Parse a qwen chat JSONL into the agent-inspect trace shape.

    Turns are delimited by real user prompts (``type==user`` with
    ``provenance==real_user``); this matches the eval's turn structure, where
    every eval turn is one ``qwen`` / ``qwen -c`` invocation whose records are
    appended to the same chat file. Assistant ``functionCall`` parts become
    steps; ``tool_result`` records (matched by functionResponse id) fill their
    outputs; assistant thought parts attach to the most recent step.
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # functionCall id -> step
    metadata: dict = {}
    pending_thought = ""

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
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        etype = event.get("type")
        message = event.get("message") or {}
        parts = message.get("parts") or []

        if etype == "user" and event.get("provenance") == "real_user":
            if not metadata:
                metadata = {
                    "session_id": event.get("sessionId"),
                    "cwd": event.get("cwd"),
                    "cli_version": event.get("version"),
                }
            current = open_turn(event.get("promptId"))
            current["agent_input"] = _text_parts(parts)
            pending_thought = ""
        elif etype == "assistant":
            if not current:
                current = open_turn()
            if metadata and not metadata.get("model") and event.get("model"):
                metadata["model"] = event.get("model")
            thought = _thought_text(parts)
            if thought:
                pending_thought = (pending_thought + "\n" + thought).strip()
            for part in parts:
                call = part.get("functionCall") if isinstance(part, dict) else None
                if not call:
                    continue
                step = {
                    "id": call.get("id"),
                    "tool": call.get("name"),
                    "tool_input_args": _tool_input_args(call.get("args")),
                    "tool_output": None,
                    "agent_thought": pending_thought or None,
                }
                current["steps"].append(step)
                if call.get("id"):
                    calls_by_id[call["id"]] = step
                pending_thought = ""
            text = _text_parts(parts)
            if text:
                current["agent_response"] = text
        elif etype == "tool_result":
            for part in parts:
                fr = part.get("functionResponse") if isinstance(part, dict) else None
                if not fr:
                    continue
                step = calls_by_id.get(fr.get("id"))
                if step is not None:
                    step["tool_output"] = _tool_output(fr.get("response"))

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    chat_text = _read_chat(container_name)
    if not chat_text:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_chat(chat_text)}))


if __name__ == "__main__":
    main()
