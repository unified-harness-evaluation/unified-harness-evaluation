from typing import List, Optional, Dict, Any

from agent_inspect.exception import InvalidInputValueError
from agent_inspect.exception.error_codes import ErrorCode
from agent_inspect.models.metrics.agent_trace import TurnTrace
from agent_inspect.models.metrics.metric_score import NumericalScore
from agent_inspect.core.utils import get_config_or_default

from agent_quality_inspect.constants import (
    TOKEN_NORMALIZATION_FACTOR,
    TOKEN_NORMALIZATION_FACTOR_DEFAULT,
    PERFORMANCE_SCORE,
    NUM_TOKENS,
    NUM_TOOL_CALLS,
    NUM_STEPS,
)


class EfficiencyMetric:
    """
    Metric to quantify how efficiently an agent achieves its goal, by normalizing its
    performance score against the resources used.

    Each method takes an already-computed performance score and the agent turn traces, and
    divides the score by a cost measure derived from the traces:

    - **efficiency_per_token**: ``performance_score / (num_tokens / token_normalization_factor)``
    - **efficiency_per_tool_call**: ``performance_score / num_tool_calls``
    - **efficiency_per_step**: ``performance_score / num_steps``

    The performance score is any numerical measure of how well the agent did; examples
    include a progress score or a capability correctness score.

    :param config: Default to ``None``. Configuration options:

        - **token_normalization_factor**: the divisor applied to the token count before
          normalizing (i.e. ``num_tokens / token_normalization_factor``). Default to ``1e6``
          (one million). Lower this (e.g. to ``1e5``) for easier test cases where fewer
          tokens are expected.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @staticmethod
    def compute_token_efficiency(
        performance_score: NumericalScore,
        num_tokens: int,
        token_normalization_factor: float = TOKEN_NORMALIZATION_FACTOR_DEFAULT,
    ) -> NumericalScore:
        """
        Computes token efficiency from raw counts, without requiring an agent trace.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param num_tokens: the total number of tokens consumed.
        :param token_normalization_factor: the divisor applied to ``num_tokens`` before
            normalizing. Default to ``1e6`` (one million).
        :return: a NumericalScore whose ``score`` is
            ``performance_score.score / (num_tokens / token_normalization_factor)``.
        :raises InvalidInputValueError: if ``num_tokens`` is zero.
        """
        if num_tokens == 0:
            raise InvalidInputValueError(
                internal_code=ErrorCode.INVALID_VALUE.value,
                message="Cannot compute token efficiency: total token consumption is zero.",
            )
        efficiency = performance_score.score / (num_tokens / token_normalization_factor)
        return NumericalScore(
            score=round(efficiency, 4),
            sub_scores={
                PERFORMANCE_SCORE: performance_score.score,
                NUM_TOKENS: num_tokens,
            },
        )

    def efficiency_per_token(
        self, performance_score: NumericalScore, agent_turn_traces: List[TurnTrace]
    ) -> NumericalScore:
        """
        Computes the performance score achieved per ``token_normalization_factor`` tokens consumed.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param agent_turn_traces: list of TurnTrace objects from the agent trajectory.
        :return: a NumericalScore for token efficiency.
        :raises InvalidInputValueError: if the total token consumption is zero.
        """
        from agent_inspect.metrics.observed.token_count import TotalTokenConsumption  # noqa: PLC0415
        token_normalization_factor = get_config_or_default(
            self.config, TOKEN_NORMALIZATION_FACTOR, TOKEN_NORMALIZATION_FACTOR_DEFAULT
        )
        num_tokens = int(TotalTokenConsumption(self.config).evaluate(agent_turn_traces).score)
        return EfficiencyMetric.compute_token_efficiency(
            performance_score, num_tokens, token_normalization_factor
        )

    @staticmethod
    def compute_tool_call_efficiency(
        performance_score: NumericalScore,
        num_tool_calls: int,
    ) -> NumericalScore:
        """
        Computes tool call efficiency from raw counts, without requiring an agent trace.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param num_tool_calls: the total number of tool calls made.
        :return: a NumericalScore whose ``score`` is
            ``performance_score.score / num_tool_calls``.
        :raises InvalidInputValueError: if ``num_tool_calls`` is zero.
        """
        if num_tool_calls == 0:
            raise InvalidInputValueError(
                internal_code=ErrorCode.INVALID_VALUE.value,
                message="Cannot compute tool call efficiency: number of tool calls is zero.",
            )
        efficiency = performance_score.score / num_tool_calls
        return NumericalScore(
            score=round(efficiency, 4),
            sub_scores={
                PERFORMANCE_SCORE: performance_score.score,
                NUM_TOOL_CALLS: num_tool_calls,
            },
        )

    def efficiency_per_tool_call(
        self, performance_score: NumericalScore, agent_turn_traces: List[TurnTrace]
    ) -> NumericalScore:
        """
        Computes the performance score achieved per tool call made.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param agent_turn_traces: list of TurnTrace objects from the agent trajectory.
        :return: a NumericalScore for tool call efficiency.
        :raises InvalidInputValueError: if the number of tool calls is zero.
        """
        from agent_inspect.metrics.observed.tool_call_count import ToolCallCount  # noqa: PLC0415
        num_tool_calls = int(ToolCallCount(self.config).evaluate(agent_turn_traces).score)
        return EfficiencyMetric.compute_tool_call_efficiency(performance_score, num_tool_calls)

    @staticmethod
    def compute_step_efficiency(
        performance_score: NumericalScore,
        num_steps: int,
    ) -> NumericalScore:
        """
        Computes step efficiency from raw counts, without requiring an agent trace.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param num_steps: the total number of steps taken.
        :return: a NumericalScore whose ``score`` is ``performance_score.score / num_steps``.
        :raises InvalidInputValueError: if ``num_steps`` is zero.
        """
        if num_steps == 0:
            raise InvalidInputValueError(
                internal_code=ErrorCode.INVALID_VALUE.value,
                message="Cannot compute step efficiency: number of steps is zero.",
            )
        efficiency = performance_score.score / num_steps
        return NumericalScore(
            score=round(efficiency, 4),
            sub_scores={
                PERFORMANCE_SCORE: performance_score.score,
                NUM_STEPS: num_steps,
            },
        )

    def efficiency_per_step(
        self, performance_score: NumericalScore, agent_turn_traces: List[TurnTrace]
    ) -> NumericalScore:
        """
        Computes the performance score achieved per step taken.

        :param performance_score: a NumericalScore whose ``score`` is used as the numerator.
        :param agent_turn_traces: list of TurnTrace objects from the agent trajectory.
        :return: a NumericalScore for step efficiency.
        :raises InvalidInputValueError: if the number of steps is zero.
        """
        from agent_inspect.metrics.observed.step_count import StepCount  # noqa: PLC0415
        num_steps = int(StepCount(self.config).evaluate(agent_turn_traces).score)
        return EfficiencyMetric.compute_step_efficiency(performance_score, num_steps)
