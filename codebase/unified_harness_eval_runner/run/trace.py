"""Trace conversion: server turn dicts -> AgentTrace, and save to disk."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from uuid import uuid4

if TYPE_CHECKING:
    from config.testcase import SkillCall


@dataclass
class ToolInputParameter:
    name: str
    value: Optional[Any] = None


@dataclass
class AgentResponse:
    response: Union[str, dict]
    status_code: Optional[str] = None


@dataclass
class Step:
    id: str
    parent_ids: List[str] = field(default_factory=list)
    tool: Optional[str] = None
    tool_input_args: List[ToolInputParameter] = field(default_factory=list)
    tool_output: Optional[Any] = None
    agent_thought: Optional[str] = None
    skill_calls: Optional[List[SkillCall]] = None


@dataclass
class TurnTrace:
    id: str
    agent_input: str = ""
    agent_response: Optional[AgentResponse] = None
    from_id: Optional[str] = None
    steps: List[Step] = field(default_factory=list)
    latency_in_ms: Optional[float] = None


@dataclass
class AgentTrace:
    turns: List[TurnTrace] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

logger = logging.getLogger(__name__)


def load_trace_from_server_turns(turns: list[dict]) -> AgentTrace:
    """Build an AgentTrace from per-turn dicts returned by the HTTP server.

    Each turn has {user_input, answer, steps: [{id, tool, tool_input_args, tool_output, ...}], usage, latency_ms}.
    """
    trace_turns: list[TurnTrace] = []
    total_tokens = 0

    for turn in turns:
        user_input = turn.get("user_input", "")
        answer = turn.get("answer", "")
        raw_steps = turn.get("steps", [])
        usage = turn.get("usage", {})

        steps: list[Step] = []
        for s in raw_steps:
            if not s.get("tool"):
                continue
            steps.append(Step(
                id=s.get("id") or str(uuid4()),
                tool=s["tool"],
                tool_input_args=[
                    ToolInputParameter(name=p["name"], value=p.get("value"))
                    for p in (s.get("tool_input_args") or [])
                ],
                tool_output=s.get("tool_output"),
                agent_thought=s.get("agent_thought"),
            ))

        total_tokens += usage.get("total", 0)

        trace_turns.append(TurnTrace(
            id=str(uuid4()),
            agent_input=user_input,
            agent_response=AgentResponse(response=answer) if answer else None,
            steps=steps,
            latency_in_ms=turn.get("latency_ms"),
        ))

    return AgentTrace(turns=trace_turns, metadata={"total_token_consumption": total_tokens})


def save_trace(trace: AgentTrace, path: Path) -> None:
    data = {
        "metadata": trace.metadata,
        "turns": [
            {
                "id": t.id,
                "agent_input": t.agent_input,
                "agent_response": {
                    "response": t.agent_response.response,
                    "status_code": t.agent_response.status_code,
                } if t.agent_response else None,
                "from_id": t.from_id,
                "latency_in_ms": t.latency_in_ms,
                "steps": [
                    {
                        "id": s.id,
                        "parent_ids": s.parent_ids,
                        "tool": s.tool,
                        "tool_input_args": [
                            {"name": p.name, "value": p.value}
                            for p in s.tool_input_args
                        ],
                        "tool_output": s.tool_output,
                        "agent_thought": s.agent_thought,
                        "skill_calls": [
                            {"skill_id": sc.skill_id, "skill_name": sc.skill_name}
                            for sc in (s.skill_calls or [])
                        ],
                    }
                    for s in t.steps
                ],
            }
            for t in trace.turns
        ],
    }
    path.write_text(json.dumps(data, indent=2, default=str))
    logger.info("Saved trace -> %s", path)
