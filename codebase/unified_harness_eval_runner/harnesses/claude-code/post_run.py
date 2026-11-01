#!/usr/bin/env python3
"""Post-run harvest for the official Anthropic Claude Code harness.

Claude Code persists the full session (every message, tool call, tool result
and token count) to a JSONL transcript at
``$HOME/.claude/projects/<cwd-hash>/<session-id>.jsonl``. Each line is one event;
assistant messages carry ``tool_use`` content blocks, the following user
messages carry the matching ``tool_result`` blocks. Multi-turn conversations
resume the SAME session (``--resume <session-id>``), so each CLI invocation
appends a fresh user prompt + its assistant/tool exchange to the same file --
the newest transcript holds the whole conversation.

The agent runs as the NON-ROOT ``coder`` user (see harness.yaml cmd
``runuser -u coder -- claude ...`` with ``HOME=/home/coder``), so the transcript
lives under coder's home, not /root. ``docker exec`` defaults to root but can
still read coder's files; we resolve coder's home explicitly.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we read the transcript out of the container and parse it
into the agent-inspect trace shape, emitting it on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}
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


def _read_transcript(container_name: str) -> str:
    """Return the newest Claude Code JSONL transcript from the container, or ''.

    The agent runs as ``coder``; resolve its HOME via getent (fall back to the
    harness-configured /home/coder) and pick the most recently modified
    transcript under ``.claude/projects``.
    """
    locate = subprocess.run(
        [
            DOCKER, "exec", container_name, "sh", "-c",
            'h=$(getent passwd coder | cut -d: -f6); [ -z "$h" ] && h=/home/coder; '
            'find "$h/.claude/projects" -name "*.jsonl" '
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


def _content_blocks(message: dict):
    """Normalise a message's content to a list of blocks.

    Claude Code content is either a plain string (a user prompt) or a list of
    typed blocks (text / thinking / tool_use / tool_result)."""
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _tool_result_text(content) -> str:
    """Flatten a tool_result's content (string, or list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(json.dumps(block))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


def _tool_input_args(tool_input) -> list:
    """A tool_use ``input`` is a dict of named params."""
    if isinstance(tool_input, dict):
        return [{"name": name, "value": value} for name, value in tool_input.items()]
    if tool_input is None:
        return []
    return [{"name": "input", "value": tool_input}]


def _is_user_prompt(event: dict) -> bool:
    """True for a real user turn-opening prompt (vs a tool_result continuation).

    Tool-result user messages carry ``toolUseResult``/``sourceToolAssistantUUID``
    and a content list of ``tool_result`` blocks; a genuine prompt has neither.
    """
    if event.get("type") != "user":
        return False
    if "toolUseResult" in event or "sourceToolAssistantUUID" in event:
        return False
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    for block in _content_blocks(message):
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return False
    return True


def parse_transcript(transcript_text: str) -> dict:
    """Parse a Claude Code JSONL transcript into the agent-inspect trace shape.

    Turns are delimited by real user prompts: each CLI invocation
    (``claude -p <task>`` / ``--resume <id> -p <task>``) appends one such prompt
    followed by its assistant/tool exchange, matching the eval's
    one-turn-per-invocation structure. Steps come from ``tool_use`` blocks, their
    outputs from the matching ``tool_result`` blocks (by ``tool_use_id``),
    assistant text accumulates into ``agent_response`` and ``thinking`` blocks
    attach to the step they precede as ``agent_thought``.
    """
    turns: list = []
    current: dict = {}
    calls_by_id: dict = {}  # tool_use id -> step, for matching tool_result
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

    for line in transcript_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        etype = event.get("type")

        # Harvest session metadata from any rich event (first wins for identity).
        if etype in ("user", "assistant") and not metadata.get("session_id"):
            metadata = {
                "session_id": event.get("sessionId"),
                "cwd": event.get("cwd"),
                "version": event.get("version"),
                "git_branch": event.get("gitBranch"),
            }

        if _is_user_prompt(event):
            current = open_turn(event.get("promptId") or event.get("uuid"))
            texts = [
                b.get("text", "")
                for b in _content_blocks(event["message"])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            current["agent_input"] = "\n".join(t for t in texts if t).strip()
            continue

        message = event.get("message")
        if not isinstance(message, dict):
            # queue-operation / last-prompt / summary scaffolding -- ignore.
            continue

        if etype == "assistant":
            if not current:
                current = open_turn()
            pending_thought = None
            responses = []
            for block in _content_blocks(message):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    thought = block.get("thinking") or block.get("text") or ""
                    if thought:
                        pending_thought = thought.strip()
                elif btype == "text":
                    text = block.get("text", "")
                    if text:
                        responses.append(text)
                elif btype == "tool_use":
                    step = {
                        "id": block.get("id"),
                        "tool": block.get("name"),
                        "tool_input_args": _tool_input_args(block.get("input")),
                        "tool_output": None,
                        "agent_thought": pending_thought,
                    }
                    pending_thought = None
                    current["steps"].append(step)
                    if block.get("id"):
                        calls_by_id[block["id"]] = step
            if responses:
                joined = "\n".join(responses).strip()
                current["agent_response"] = (
                    (current["agent_response"] + "\n" + joined).strip()
                    if current["agent_response"] else joined
                )
            # A trailing thinking block with no following tool_use attaches to the
            # most recent step so reasoning is not lost.
            if pending_thought and current["steps"] and not current["steps"][-1]["agent_thought"]:
                current["steps"][-1]["agent_thought"] = pending_thought
            usage = message.get("usage")
            if isinstance(usage, dict) and usage:
                current["token_usage"] = usage

        elif etype == "user":
            # Tool-result continuation: route each result to its step.
            if not current:
                current = open_turn()
            for block in _content_blocks(message):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    step = calls_by_id.get(block.get("tool_use_id"))
                    if step is not None:
                        step["tool_output"] = _tool_result_text(block.get("content"))

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    transcript_text = _read_transcript(container_name)
    if not transcript_text:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_transcript(transcript_text)}))


if __name__ == "__main__":
    main()
