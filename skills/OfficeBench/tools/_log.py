import functools
import inspect
import json
import os
import time


def _log_path() -> str:
    explicit = os.environ.get("TOOL_CALL_LOG")
    if explicit:
        return explicit
    # Local run: write to skills/OfficeBench/scripts/tool_calls.jsonl so
    # user_proxy_driver.skill_tool_call_logs() picks it up automatically.
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(skill_root, "scripts", "tool_calls.jsonl")


def log_tool_call(tool_name: str):
    """Decorator: appends a tool-call record to tool_calls.jsonl after each invocation.

    Record format:
        {"tool": "...", "args": {...}, "output": "...", "duration_ms": ..., "ts": ...}
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            result = fn(*args, **kwargs)
            duration_ms = (time.time() - t0) * 1000
            try:
                sig = inspect.signature(fn)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                entry = {
                    "tool": tool_name,
                    "args": dict(bound.arguments),
                    "output": result,
                    "duration_ms": round(duration_ms, 1),
                    "ts": t0,
                }
                path = _log_path()
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                pass
            return result
        return wrapper
    return decorator
