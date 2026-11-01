"""ToolSandboxAssistant tool library.

Self-contained port of Apple ToolSandbox's mock-assistant tools. The original
tools operated on a shared in-process Polars ``ExecutionContext``; this port
swaps that state layer for the unified per-task ``world.db`` (``ts_*`` tables;
see ``db.py``) so the tools can run as standalone CLI commands inside a Claude
skill.

Tool names, signatures and semantics are preserved.
"""
