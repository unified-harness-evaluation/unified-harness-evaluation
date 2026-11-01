"""LLM-based simulated user for driving conversations.

Thin wrapper around agent_inspect's UserProxyAgent, matching the interface
used in CUGA's experiment_clean runner.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from agent_quality_inspect.litellm_client import LiteLLMClient
from agent_inspect.models.user_proxy.chat import (
    ChatHistory,
    UserProxyMessage,
)
from agent_inspect.models.user_proxy.terminating_condition import TerminatingCondition
from agent_inspect.user_proxy import UserProxyAgent

logger = logging.getLogger(__name__)

UP_MAX_RETRIES = 3


class UserProxy:
    """Wraps agent_inspect's UserProxyAgent with retry logic."""

    def __init__(
        self,
        model: str,
        max_tokens: int,
        task_summary: str,
        use_expert_agent: bool = True,
        initial_message: str = "",
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self.initial_message = initial_message

        if api_key:
            os.environ.setdefault("AZURE_AI_API_KEY", api_key)
        if api_base:
            os.environ.setdefault("AZURE_AI_API_BASE", api_base)

        llm_client = LiteLLMClient(model=model, max_tokens=max_tokens)
        self._agent = UserProxyAgent(
            llm_client=llm_client,
            task_summary=task_summary,
            terminating_conditions=[TerminatingCondition()],
            config={"use_expert_agent": use_expert_agent},
        )

    async def generate_message(self, chat: ChatHistory) -> Optional[UserProxyMessage]:
        if not chat.conversations and self.initial_message:
            return UserProxyMessage(message_str=self.initial_message)

        for attempt in range(UP_MAX_RETRIES):
            try:
                return await self._agent.generate_message_from_chat_history(chat)
            except Exception as exc:
                exc_str = str(exc).lower()
                _is_transient = (
                    "060011" in exc_str
                    or "060010" in exc_str
                    or "empty user proxy message" in exc_str
                )
                if _is_transient and attempt < UP_MAX_RETRIES - 1:
                    _wait = 2 ** attempt
                    logger.warning(
                        "User proxy transient error (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, UP_MAX_RETRIES, _wait, exc,
                    )
                    await asyncio.sleep(_wait)
                elif _is_transient:
                    logger.warning("User proxy ended after %d retries: %s", UP_MAX_RETRIES, exc)
                    return None
                else:
                    logger.error("User proxy fatal error: %s", exc, exc_info=True)
                    raise

        return None
