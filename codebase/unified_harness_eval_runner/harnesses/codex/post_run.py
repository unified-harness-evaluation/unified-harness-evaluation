#!/usr/bin/env python3
"""Post-run harvest for the codex harness.

Codex streams the full session (every reasoning step, tool call, tool output and
token count) to a rollout JSONL at ``$HOME/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``.
Multi-turn conversations resume the SAME rollout (``codex exec resume --last``),
so the newest rollout holds the whole conversation.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the rollout out of the container and parse it into
the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Token usage is NOT emitted here: codex's LLM traffic goes through the eval's /v1
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


def _read_rollout(container_name: str) -> str:
    """Return the newest rollout JSONL from the container, or '' if none."""
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'find "$HOME/.codex/sessions" -name "rollout-*.jsonl" '
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


def _message_text(payload: dict) -> str:
    """Join the text segments of a response_item/message payload."""
    parts = []
    for chunk in payload.get("content") or []:
        if chunk.get("type") in ("input_text", "output_text", "text"):
            parts.append(chunk.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _tool_input_args(arguments) -> list:
    """Codex function-call arguments is a JSON string of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def parse_rollout(rollout_text: str) -> dict:
    """Parse a codex rollout JSONL into the agent-inspect trace shape.

    Turns are delimited by event_msg/task_started events (each carries a turn_id);
    this matches the eval's turn structure, where every eval turn is one
    ``codex exec`` / ``codex exec resume --last`` invocation appended to the file.
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # call_id -> step, for matching function_call_output
    metadata: dict = {}

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

    for line in rollout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        event_type = event.get("type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        payload_type = payload.get("type")

        if event_type == "session_meta":
            metadata = {
                "session_id": payload.get("session_id"),
                "cwd": payload.get("cwd"),
                "cli_version": payload.get("cli_version"),
                "model_provider": payload.get("model_provider"),
            }
        elif event_type == "event_msg" and payload_type == "task_started":
            current = open_turn(payload.get("turn_id"))
        elif event_type == "response_item" and payload_type == "message":
            if not current:
                current = open_turn()
            role = payload.get("role")
            text = _message_text(payload)
            if not text:
                continue
            # developer messages are system/skills/permissions scaffolding; the
            # user's <environment_context> block is harness-injected, not the task.
            if role == "user" and not text.startswith("<environment_context>"):
                current["agent_input"] = text
            elif role == "assistant":
                current["agent_response"] = text
        elif event_type == "response_item" and payload_type == "function_call":
            if not current:
                current = open_turn()
            step = {
                "id": payload.get("call_id") or payload.get("id"),
                "tool": payload.get("name"),
                "tool_input_args": _tool_input_args(payload.get("arguments")),
                "tool_output": None,
                "agent_thought": None,
            }
            current["steps"].append(step)
            if payload.get("call_id"):
                calls_by_id[payload["call_id"]] = step
        elif event_type == "response_item" and payload_type == "function_call_output":
            step = calls_by_id.get(payload.get("call_id"))
            if step is not None:
                step["tool_output"] = payload.get("output")
        elif event_type == "response_item" and payload_type == "reasoning":
            # codex reasoning summaries attach to the most recent step as thought
            if current and current["steps"]:
                summary = payload.get("summary") or payload.get("text")
                if isinstance(summary, list):
                    summary = "\n".join(
                        s.get("text", "") if isinstance(s, dict) else str(s)
                        for s in summary
                    ).strip()
                if summary:
                    current["steps"][-1]["agent_thought"] = summary
        elif event_type == "token_usage_record":
            if not current:
                current = open_turn(payload.get("turn_id"))
            current["token_usage"] = (
                payload.get("turn_token_usage") or payload.get("usage") or {}
            )

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    rollout_text = _read_rollout(container_name)
    if not rollout_text:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_rollout(rollout_text)}))


if __name__ == "__main__":
    main()
