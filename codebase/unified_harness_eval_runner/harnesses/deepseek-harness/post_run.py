#!/usr/bin/env python3
"""Post-run harvest for the deepseek-harness (``dsh``) harness.

DeepSeek's ``dsh`` persists the full session transcript -- every user/assistant
message, tool call, tool result and per-inference token usage -- as an append-only
event log at::

    $HOME/.dsh/sessions/<project>/session-<uuid>/session.v4.jsonl.zstd

(HOME is ``/root`` in this image.) The log is logically JSONL (one event object per
line), but each appended batch of events is flushed as its OWN zstd frame, so the
file is a concatenation of many zstd frames rather than a single stream. Multi-turn
conversations resume the SAME session (``dsh --session-id <id>`` appends more
``turn/start`` ... ``turn/end`` brackets to this one file), so the newest session
file holds the whole conversation.

Event schema (``data`` payload abbreviated):

* ``session``            -- header: id, cwd, version, createdAt (metadata).
* ``turn/start``         -- ``{turn}``; opens one eval turn (= one CLI invocation).
* ``user/message``       -- ``{content:[{type:text,text}], source:{kind}}``. The
  real task prompt has ``source.kind == "user"``; ``runtime-context`` snapshots are
  harness-injected scaffolding and are skipped.
* ``assistant/message``  -- ``{message:{content:[{type:"text"|"tool-call",...}]},
  usage:{inputTokens,outputTokens,...}}``. Text blocks preceding a tool-call are the
  step's thought; text in a tool-call-less message is the turn's spoken response.
* ``tool/result``        -- ``{message:{toolCallId, content:[{type:text,text}],
  isError}}``; matched to its call by ``toolCallId``.
* ``turn/end``           -- closes the turn.

This runs on the HOST while the container is still alive (server.container.close()
invokes it right before teardown). When ``capture_trajectory`` is set in this
harness's harness.yaml, we decompress the event log out of the container -- using
the container's own ``node`` (``dsh`` is a node app, so node is always present, and
node 22 ships ``zlib.zstdDecompressSync``; there is no zstd CLI in the image) --
splitting on each zstd frame boundary so every appended batch is recovered, then
parse the events into the agent-inspect trace shape and emit on stdout as::

    {"trajectory": {"turns": [...], "metadata": {...}}}

Turn alignment: the shared merge code folds our ``turns[i].steps`` into the eval's
turns BY INDEX, and each eval turn is one ``dsh`` / ``dsh --session-id`` (resume)
invocation appended to the SAME session. We open a new turn at every ``turn/start``
event, in order, so N invocations yield N turns.
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

# Node program (run inside the container with `node -`) that locates the newest
# dsh session event log and dumps its decompressed JSONL to stdout. The log is a
# concatenation of independent zstd frames (one per appended batch), which
# zstdDecompressSync decodes one-at-a-time, so we split on every zstd magic
# (0x28 0xB5 0x2F 0xFD) and decode each frame from that offset (the decoder stops
# at the first frame, ignoring the trailing ones). Spurious magic bytes inside a
# frame's payload simply fail to decode and are skipped.
_DUMP_SCRIPT = r"""
const fs = require("fs");
const cp = require("child_process");
const z = require("zlib");
if (typeof z.zstdDecompressSync !== "function") { process.exit(0); }
const base = (process.env.HOME || "/root") + "/.dsh/sessions";
let found = "";
try {
  found = cp.execSync(
    "find " + base + " -type f -name 'session.v4.jsonl.zstd' " +
    "-printf '%T@ %p\\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-"
  ).toString().trim();
} catch (e) {}
if (!found) { process.exit(0); }
let buf;
try { buf = fs.readFileSync(found); } catch (e) { process.exit(0); }
const out = [];
for (let i = 0; i + 4 <= buf.length; i++) {
  if (buf[i] === 0x28 && buf[i + 1] === 0xb5 && buf[i + 2] === 0x2f && buf[i + 3] === 0xfd) {
    try { out.push(z.zstdDecompressSync(buf.subarray(i)).toString("utf8")); } catch (e) {}
  }
}
process.stdout.write(out.join(""));
"""


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


def _read_events(container_name: str) -> list:
    """Decompress dsh's session event log out of the container and return the
    parsed events in log order, or [] when none is found."""
    proc = subprocess.run(
        [DOCKER, "exec", "-i", container_name, "node", "-"],
        input=_DUMP_SCRIPT,
        capture_output=True,
        text=True,
        check=False,
    )
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return events


def _message_text(content) -> str:
    """Join the text segments of a message's content array."""
    parts = []
    for chunk in content or []:
        if isinstance(chunk, dict) and chunk.get("type") == "text":
            parts.append(chunk.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _tool_input_args(arguments) -> list:
    """dsh stores a tool-call's arguments as a JSON string of named params."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            return [{"name": "arguments", "value": arguments}]
    if isinstance(arguments, dict):
        return [{"name": name, "value": value} for name, value in arguments.items()]
    return [{"name": "arguments", "value": arguments}]


def _accumulate_tokens(acc: dict, usage: dict) -> None:
    """Fold an assistant message's usage into the turn accumulator."""
    if not isinstance(usage, dict):
        return
    acc["input"] += usage.get("inputTokens") or 0
    acc["output"] += usage.get("outputTokens") or 0
    acc["cache_read"] += usage.get("cacheReadTokens") or 0
    acc["cache_write"] += usage.get("cacheWriteTokens") or 0
    acc["total"] += usage.get("totalTokens") or 0


def parse_events(events: list) -> dict:
    """Parse dsh session events into the agent-inspect trace shape.

    A new turn opens at each ``turn/start`` (one ``dsh`` invocation). Within a
    turn, assistant ``tool-call`` blocks become steps (the text preceding a
    tool-call is its thought), ``tool/result`` events fill in each step's output
    by ``toolCallId``, and a tool-call-less assistant message is the turn's
    spoken response.
    """
    turns: list = []
    current: dict | None = None
    calls_by_id: dict = {}  # toolCallId -> step, scoped to the current turn
    metadata: dict = {}

    def open_turn(turn_id=None) -> dict:
        nonlocal calls_by_id
        turn = {
            "turn_id": turn_id,
            "agent_input": "",
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

    for event in events:
        etype = event.get("type")
        data = event.get("data")

        if etype == "session":
            metadata = {
                "session_id": event.get("id"),
                "cwd": event.get("cwd"),
                "version": event.get("version"),
                "created_at": event.get("createdAt"),
            }
            continue

        if not isinstance(data, dict):
            continue

        if etype == "turn/start":
            turn_no = data.get("turn")
            current = open_turn(str(turn_no) if turn_no is not None else None)
            continue

        if etype == "user/message":
            # Only the actual task prompt is the turn input; runtime-context
            # snapshots are harness-injected scaffolding.
            if (data.get("source") or {}).get("kind") != "user":
                continue
            if current is None:
                current = open_turn()
            if not current["agent_input"]:
                current["agent_input"] = _message_text(data.get("content"))
            continue

        if etype == "assistant/message":
            if current is None:
                current = open_turn()
            message = data.get("message") or {}
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
                elif btype == "tool-call":
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
            # Text in a tool-call-less message is the turn's spoken answer; keep
            # the latest such message.
            if pending_text and not had_tool_call:
                current["agent_response"] = "\n".join(pending_text)
            _accumulate_tokens(current["token_usage"], data.get("usage"))
            continue

        if etype == "tool/result":
            message = data.get("message") or {}
            call_id = message.get("toolCallId") or (message.get("source") or {}).get("callId")
            step = calls_by_id.get(call_id)
            if step is not None:
                step["tool_output"] = _message_text(message.get("content"))
            continue

    return {"turns": turns, "metadata": metadata}


def main() -> None:
    container_name = sys.argv[1]
    if not _capture_enabled():
        print("{}")
        return
    events = _read_events(container_name)
    if not events:
        print(json.dumps({"trajectory": {"turns": [], "metadata": {}}}))
        return
    print(json.dumps({"trajectory": parse_events(events)}))


if __name__ == "__main__":
    main()
