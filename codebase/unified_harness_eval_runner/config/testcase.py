"""Parse YAML test cases into typed criteria for conversation and evaluation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import yaml


# ── Evaluation criteria (used by testcase parsing and traceless judge) ──────


class SubGoalCategory(Enum):
    OUTPUT_RULE = "agent_response"
    TOOL_CALL_RULE = "tool_call"
    COMPLIANCE_RULE = "rule_compliance"
    MEMORY_RULE = "memory_agent_response"


@dataclass
class SubGoal:
    details: str
    category: Optional[SubGoalCategory] = None


@dataclass
class SkillCall:
    skill_id: str
    skill_name: Optional[str] = None


@dataclass
class CapabilityOutput:
    check: str


@dataclass
class ExpectedCapability:
    description: str
    capability_name: Optional[str] = None
    expected_output: Optional[CapabilityOutput] = None


@dataclass
class TestCaseCriteria:
    case_id: str
    task_summary: str
    max_turns: int
    sub_goals: list[SubGoal] = field(default_factory=list)
    memory_sub_goals: list[SubGoal] = field(default_factory=list)
    expected_skill_calls: list[SkillCall] = field(default_factory=list)
    expected_capabilities: list[ExpectedCapability] = field(default_factory=list)


def _find_dynamic_step(case: dict[str, Any]) -> dict[str, Any]:
    for step in case.get("test_steps", []):
        if step.get("type") == "dynamic_conversation":
            return step
    raise ValueError("No dynamic_conversation step found in test case")


_IGNORED_TOOLS = {"skill0_artifacts"}


def _parse_tools(step: dict[str, Any]) -> list[SkillCall]:
    skill_val = step.get("skill_validations") or {}
    return [
        SkillCall(skill_id=s["skill"], skill_name=s["skill"])
        for s in (skill_val.get("expected_skill_invocations") or [])
        if s.get("skill") and s["skill"] not in _IGNORED_TOOLS
    ]


def _parse_capabilities(step: dict[str, Any]) -> list[ExpectedCapability]:
    cap_val = step.get("capability_validations") or {}
    caps = []
    for c in cap_val.get("expected_capabilities") or []:
        desc = c.get("description")
        if not desc:
            raise ValueError(f"Expected capability missing 'description': {c}")
        raw_out = c.get("output")
        cap_out = CapabilityOutput(check=raw_out["check"]) if raw_out and raw_out.get("check") else None
        caps.append(ExpectedCapability(
            capability_name=c.get("name", None),
            description=desc,
            expected_output=cap_out,
        ))
    return caps


def parse_test_case(path: str) -> TestCaseCriteria:
    with open(path, "r", encoding="utf-8") as f:
        case = yaml.safe_load(f)

    case_id = str(case.get("id", os.path.splitext(os.path.basename(path))[0]))
    step = _find_dynamic_step(case)

    sub_goals = [
        SubGoal(details=v["check"], category=SubGoalCategory.OUTPUT_RULE)
        for v in (step.get("agent_response_validations") or [])
        if v.get("check")
    ]

    # Memory-based subgoals: graded by the same validator as normal subgoals but
    # kept in a separate bucket so they are scored and displayed independently.
    memory_sub_goals = [
        SubGoal(details=v["check"], category=SubGoalCategory.MEMORY_RULE)
        for v in (step.get("memory_agent_response_validations") or [])
        if v.get("check")
    ]

    return TestCaseCriteria(
        case_id=case_id,
        task_summary=(step.get("user_agent") or {}).get("task_summary", ""),
        max_turns=step.get("max_turns", 10),
        sub_goals=sub_goals,
        memory_sub_goals=memory_sub_goals,
        expected_skill_calls=_parse_tools(step),
        expected_capabilities=_parse_capabilities(step),
    )


def iter_case_files(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        found = []
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f.endswith((".yaml", ".yml")) and f != "skills_config.yaml":
                    found.append(os.path.join(root, f))
        if not found:
            raise ValueError(f"No .yaml files found under {path}")
        return sorted(found)
    raise FileNotFoundError(f"Not a file or directory: {path}")
