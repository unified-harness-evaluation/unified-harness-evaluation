#!/usr/bin/env python3
"""STATE-Bench portable domain skill CLI.

Commands:
  tools                                      Print the domain tool schemas (OpenAI function format).
  call  <tool> --args '<json>' [--now <iso>]  Run a tool against the unified world.db (reads/mutates it).
  reset                                      Clear this skill's multi-step session gates (no-op on data).

State model: domain data lives in the unified per-task `world.db` (seeded fresh
into /workspace by the runner). `ENV_DATA_CLASS.load()` reads this skill's scoped
slice from world.db and `.save()` writes mutations straight back — there is no
db.json seed and no state.json working copy. Multi-step gates (policy-check ->
preview -> confirm) still persist in a local `session.json` under the workspace
(fresh per task since skills upload clean into each sandbox). `reset` clears those
gates; the data itself is re-seeded per task by the runner. By default the session
file lives in `<skill>/.state/`; override with --workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from domain_meta import DEFAULT_NOW, DEFAULT_USER, ENV_CLASS, ENV_DATA_CLASS, SAVE_MAP  # noqa: E402
from tools import TOOL_SCHEMAS, WRITE_TOOL_NAMES  # noqa: E402


# --- session-state (sets/tuples) JSON codec -------------------------------
def _enc(o):
    if isinstance(o, set):
        return {"__set__": [_enc(x) for x in o]}
    if isinstance(o, tuple):
        return {"__tuple__": [_enc(x) for x in o]}
    if isinstance(o, dict):
        return {k: _enc(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_enc(x) for x in o]
    return o


def _dec(o):
    if isinstance(o, dict):
        if set(o.keys()) == {"__set__"}:
            return {_dec(x) for x in o["__set__"]}
        if set(o.keys()) == {"__tuple__"}:
            return tuple(_dec(x) for x in o["__tuple__"])
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dec(x) for x in o]
    return o


def _emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def _workspace(args) -> Path:
    return Path(args.workspace) if getattr(args, "workspace", None) else (HERE / ".state")


def _seed_if_needed(ws: Path) -> Path:
    """Ensure the workspace dir exists and return the (session-only) state path.

    Domain data now lives in world.db (see schemas.py), so there is no db.json to
    copy; this just guarantees the workspace dir for session.json.
    """
    ws.mkdir(parents=True, exist_ok=True)
    return ws / "state.json"


def cmd_tools(_args):
    _emit({"write_tools": WRITE_TOOL_NAMES, "default_user": DEFAULT_USER, "now": DEFAULT_NOW, "tools": TOOL_SCHEMAS})


def cmd_reset(args):
    ws = _workspace(args)
    for name in ("state.json", "session.json"):
        p = ws / name
        if p.exists():
            p.unlink()
    _emit({"ok": True, "reset": True, "workspace": str(ws),
           "note": "session gates cleared; domain data is re-seeded per task from world.db"})


def cmd_call(args):
    ws = _workspace(args)
    state_path = _seed_if_needed(ws)
    now = args.now or DEFAULT_NOW
    try:
        params = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as e:
        _emit({"error": f"--args must be valid JSON: {e}"}, 1)
    if not isinstance(params, dict):
        _emit({"error": "--args must be a JSON object"}, 1)

    env_data = ENV_DATA_CLASS.load(state_path)
    env = ENV_CLASS(env_data, now=now)

    session_path = ws / "session.json"
    if session_path.exists():
        for k, v in _dec(json.loads(session_path.read_text())).items():
            setattr(env, k, v)

    handler = env.tool_handlers.get(args.tool)
    if handler is None:
        _emit({"error": f"Unknown tool '{args.tool}'. Run `tools` to list available tools."}, 1)

    try:
        result = handler(params)
    except Exception as e:  # domain handlers raise on bad input; surface as JSON
        _emit({"error": f"{type(e).__name__}: {e}"}, 1)

    # Persist mutated DB (rebuild EnvironmentData from live indexes so created rows are captured).
    rebuilt = ENV_DATA_CLASS(**{field: list(getattr(env, attr).values()) for field, attr in SAVE_MAP.items()})
    rebuilt.save(state_path)

    # Persist multi-step session flags (policy-check / preview gates).
    sess_out = {k: v for k, v in vars(env).items() if k.startswith("_")}
    session_path.write_text(json.dumps(_enc(sess_out), indent=2))

    is_write = args.tool in WRITE_TOOL_NAMES
    _emit({"tool": args.tool, "is_write": is_write, "result": result})


def main():
    p = argparse.ArgumentParser(description="STATE-Bench portable domain skill CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tools").set_defaults(fn=cmd_tools)
    pr = sub.add_parser("reset")
    pr.add_argument("--workspace", default=None)
    pr.set_defaults(fn=cmd_reset)
    pc = sub.add_parser("call")
    pc.add_argument("tool")
    pc.add_argument("--args", default="{}")
    pc.add_argument("--now", default=None)
    pc.add_argument("--workspace", default=None)
    pc.set_defaults(fn=cmd_call)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
