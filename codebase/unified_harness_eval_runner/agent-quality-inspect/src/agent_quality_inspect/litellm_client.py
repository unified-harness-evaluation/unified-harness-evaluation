import asyncio
import backoff
import litellm  # type: ignore
from litellm import acompletion, get_supported_openai_params, supports_response_schema  # type: ignore
from typing import Dict, Any, Optional
import logging

from openai import APIStatusError

from agent_inspect.metrics.constants import (
    STATUS_200,
    STATUS_429,
    MAX_RETRY_ATTEMPTS_EXCEEDED,
    STATUS_500,
    STATUS_404,
)
from agent_inspect.clients.llm_client import LLMClient
from agent_inspect.exception import InvalidInputValueError
from agent_inspect.models.llm_response import LLMResponse
from agent_inspect.models.llm_payload import LLMPayload
from agent_inspect.exception.error_codes import ErrorCode, ClientComponent

logger = logging.getLogger(__name__)


def _backoff_handler(details):
    logger.warning(
        "Backing off %s (args=%s, kwargs=%s) for %.1fs "
        "(tries=%s, elapsed=%.1fs, exception: %s)",
        details["target"].__name__,
        details["args"],
        details["kwargs"],
        details["wait"],
        details["tries"],
        details["elapsed"],
        details["exception"],
    )


def _give_up_handler(details):
    logger.error(
        "Max retries reached for %s (args=%s, kwargs=%s, elapsed=%.1fs, exception: %s)",
        details["target"].__name__,
        details["args"],
        details["kwargs"],
        details["elapsed"],
        details["exception"],
    )


def _is_non_retryable(exc):
    return isinstance(
        exc,
        (
            litellm.exceptions.AuthenticationError,
            litellm.exceptions.BadRequestError,
            litellm.exceptions.NotFoundError,
            litellm.exceptions.PermissionDeniedError,
        ),
    )


class LiteLLMClient(LLMClient):
    """
    LiteLLM client override — provided because agent-quality-inspect (PyPI 2.3.6a1)
    ships the lazy-load stub in clients/__init__.py but not the implementation module.

    :param model: LiteLLM model string.
    :param max_tokens: Maximum tokens for the LLM to generate.
    :param temperature: Sampling temperature. Default ``0``.
    :param extra_params: Additional parameters forwarded to the LiteLLM API.
    """

    def __init__(
        self,
        model: str,
        max_tokens: int,
        temperature: float = 0,
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_params = extra_params or {}
        litellm.set_verbose = False

    @backoff.on_exception(
        backoff.expo,
        (litellm.exceptions.RateLimitError, litellm.exceptions.ServiceUnavailableError, Exception),
        max_tries=10,
        max_time=300,
        jitter=None,
        on_backoff=_backoff_handler,
        on_giveup=_give_up_handler,
        giveup=_is_non_retryable,
    )
    async def _make_llm_request_with_retry(self, prompt: str):
        messages = [{"role": "user", "content": prompt}]
        return await acompletion(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            **self.extra_params,
        )

    async def make_llm_request(self, prompt: str) -> LLMResponse:
        try:
            resp = await self._make_llm_request_with_retry(prompt)
            return LLMResponse(status=STATUS_200, completion=resp.choices[0].message.content)
        except litellm.exceptions.RateLimitError:
            return LLMResponse(status=STATUS_429, completion="", error_message=MAX_RETRY_ATTEMPTS_EXCEEDED)
        except APIStatusError as e:
            return LLMResponse(status=e.status_code, completion="", error_message=f"Azure OpenAI API Error: {e.message}")
        except Exception as e:
            return LLMResponse(status=int(getattr(e, "status_code", STATUS_500)), completion="", error_message=f"Unexpected error: {e}")

    async def make_llm_requests(self, prompts: list[str]) -> list[LLMResponse]:
        return list(await asyncio.gather(*(self.make_llm_request(p) for p in prompts)))

    def _convert_payload(self, payload: LLMPayload) -> Dict[str, Any]:
        messages = []
        if payload.system_prompt:
            messages.append({"role": "system", "content": payload.system_prompt})
        messages.append({"role": "user", "content": payload.user_prompt})
        raw: Dict[str, Any] = {
            "model": payload.model if payload.model else self.model,
            "messages": messages,
            "temperature": payload.temperature if payload.temperature else self.temperature,
            "max_tokens": payload.max_tokens if payload.max_tokens else self.max_tokens,
        }
        if not payload.structured_output:
            return raw
        params = get_supported_openai_params(model=raw["model"])
        if "response_format" not in params:
            raise InvalidInputValueError(
                internal_code=ErrorCode.UNSUPPORTED_ATTRIBUTION_TYPE.value,
                message="Model does not support response_format parameter.",
                component_code=ClientComponent.CLIENT_ERROR_CODE.value,
            )
        if not supports_response_schema(model=raw["model"]):
            raise InvalidInputValueError(
                internal_code=ErrorCode.UNSUPPORTED_ATTRIBUTION_TYPE.value,
                message="Model does not support response schema.",
                component_code=ClientComponent.CLIENT_ERROR_CODE.value,
            )
        raw["response_format"] = payload.structured_output
        return raw

    @backoff.on_exception(
        backoff.expo,
        (litellm.exceptions.RateLimitError, litellm.exceptions.ServiceUnavailableError, Exception),
        max_tries=10,
        max_time=300,
        jitter=None,
        on_backoff=_backoff_handler,
        on_giveup=_give_up_handler,
        giveup=_is_non_retryable,
    )
    async def _make_request_with_payload_retry(self, payload: LLMPayload):
        raw = self._convert_payload(payload)
        return await acompletion(**raw, **self.extra_params)

    async def make_request_with_payload(self, payload: LLMPayload) -> LLMResponse:
        try:
            resp = await self._make_request_with_payload_retry(payload)
            return LLMResponse(status=STATUS_200, completion=resp.choices[0].message.content)
        except InvalidInputValueError as e:
            return LLMResponse(status=STATUS_404, completion="", error_message=e.message)
        except litellm.exceptions.RateLimitError:
            return LLMResponse(status=STATUS_429, completion="", error_message=MAX_RETRY_ATTEMPTS_EXCEEDED)
        except APIStatusError as e:
            return LLMResponse(status=e.status_code, completion="", error_message=e.message)
        except Exception as e:
            return LLMResponse(status=int(getattr(e, "status_code", STATUS_500)), completion="", error_message=f"Unexpected error: {e}")
