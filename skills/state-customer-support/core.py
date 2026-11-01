"""Vendored domain-agnostic base classes (from state_bench). Stdlib only."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class DictMixin:
    """Standard to_dict/from_dict for flat dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        return {fn: getattr(self, fn) for fn in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BaseEnvironment(ABC):
    """Abstract base for domain environments."""

    def __init__(self, env_data: Any, now: str):
        self.now = now

    @property
    @abstractmethod
    def tool_handlers(self) -> dict[str, Callable]:
        ...

    @abstractmethod
    def get_full_snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        ...

    @staticmethod
    def parse_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
