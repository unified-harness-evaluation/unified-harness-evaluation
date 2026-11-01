"""Lightweight efficiency helpers for the traceless runner.

``agent_inspect``'s :class:`~agent_inspect.metrics.scorer.efficiency.EfficiencyMetric`
derives its denominators (tokens, tool calls, steps) from the trace *steps*. In the
dialogue-only traceless runner those steps are always empty, so its trace-based
instance methods (e.g. ``efficiency_per_step``) would see a count of zero and raise.

These helpers compute ``efficiency = performance_score / cost`` directly from raw
counts that DO exist in the traceless data — the number of dialogue turns and the
``llm_calls`` recorded in ``usage.json`` — without touching the trace. Token
efficiency still uses the agent-inspect static helper ``compute_token_efficiency``,
which already works off a raw ``num_tokens`` count.
"""

from __future__ import annotations

from typing import Optional


def _efficiency(performance_score: float, count: Optional[int]) -> Optional[float]:
    """``performance_score / count`` rounded to 4 dp, or ``None`` if ``count`` is
    zero/absent (mirrors how token/latency totals degrade to ``None``)."""
    if not count:
        return None
    return round(performance_score / count, 4)


def efficiency_per_turn(
    performance_score: float, num_turns: Optional[int]
) -> Optional[float]:
    """Performance score achieved per dialogue turn.

    :param performance_score: numerical performance measure (e.g. a progress score).
    :param num_turns: number of dialogue turns taken.
    :return: ``performance_score / num_turns`` rounded to 4 dp, or ``None`` when
        ``num_turns`` is zero/absent.
    """
    return _efficiency(performance_score, num_turns)


def efficiency_per_llm_calls(
    performance_score: float, num_llm_calls: Optional[int]
) -> Optional[float]:
    """Performance score achieved per LLM call.

    :param performance_score: numerical performance measure (e.g. a progress score).
    :param num_llm_calls: number of LLM calls made (from ``usage.json``).
    :return: ``performance_score / num_llm_calls`` rounded to 4 dp, or ``None`` when
        ``num_llm_calls`` is zero/absent.
    """
    return _efficiency(performance_score, num_llm_calls)
