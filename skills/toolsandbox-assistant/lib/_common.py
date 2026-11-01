"""Shared sentinels, the no-op tool decorator, and local exception types.

These mirror the pieces the original ToolSandbox tools imported from
``tool_sandbox.common`` so the ported modules stay as close to the originals
as possible.
"""

from typing import Any, Callable


class NotGiven:
    """Sentinel for an argument that was not provided.

    Distinct from ``None`` (which is an explicit, meaningful value for optional
    fields such as a reminder's latitude/longitude).
    """

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()


def register_as_tool(*_args: Any, **_kwargs: Any) -> Callable[[Callable], Callable]:
    """No-op stand-in for the original registration decorator.

    In ToolSandbox this wired functions into the sandbox registry with a
    ``visible_to`` role list. Here dispatch is explicit (see ``tools.py``), so
    the decorator only needs to leave the function untouched — kept so the
    ported source reads like the original.
    """

    def decorator(func: Callable) -> Callable:
        return func

    return decorator


# ── Local exception types ────────────────────────────────────────────────────
# The originals came from ``polars.exceptions``. We reproduce the same names so
# the error ``type`` surfaced in the CLI envelope matches the original mock's
# contract (e.g. adding a second self-contact raises ``DuplicateError``).
class DuplicateError(Exception):
    """Raised when a uniqueness invariant would be violated."""


class NoDataError(Exception):
    """Raised when a lookup by id finds no matching row."""
