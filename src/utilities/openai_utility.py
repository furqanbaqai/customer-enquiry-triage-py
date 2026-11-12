"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Provides an environment-configured OpenAI-compatible endpoint utility.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import json
from collections.abc import Callable
from time import perf_counter
from typing import Any, Final

from openai import OpenAI

from src.config import ConfigLoader
from src.utilities import Logging


class OpenAIConfigurationError(ValueError):
    """Raised when the OpenAI endpoint configuration is missing or invalid."""


class OpenAIUtility:
    """Submit prompts using environment-backed OpenAI SDK parameters."""

    _DEFAULT_MODEL: Final = "default"
    _CHAT_COMPLETIONS_PATH: Final = "/chat/completions"

    def __init__(
        self,
        configuration_getter: Callable[..., object] = ConfigLoader.get,
        client_factory: Callable[..., OpenAI] = OpenAI,
    ) -> None:
        self._configuration_getter = configuration_getter
        self._client_factory = client_factory

    def call(self, prompt: str) -> str:
        """Send ``prompt`` to the configured endpoint and return its text response."""
        if not prompt.strip():
            raise ValueError("[ERR-18] The OpenAI prompt must not be blank")
        started_at = perf_counter()

        endpoint_url = self._required_string("OFTL_OPENAI_URL")
        api_token = self._required_string("OFTL_OPENAI_APITOKEN")
        temperature = self._float_setting("OFTL_OPENAI_TEMPERATURE", 0.1, 0.0, 2.0)
        top_p = self._float_setting("OFTL_OPENAI_TOP_P", 0.9, 0.0, 1.0)
        max_tokens = self._int_setting("OFTL_OPENAI_MAX_TOKENS", 200, minimum=1)
        timeout = self._int_setting("OFTL_OPENAI_TIMEOUT", 300, minimum=1)
        stream = self._bool_setting("OFTL_OPENAI_STREAM", False)
        model = self._model_setting()
        model_type = self._required_string("OFTL_OPENAI_MODEL_TYPE")
        max_completion_tokens = (
            self._int_setting("OFTL_OPENAI_MAX_COMPLETION_TOKENS", 25_000, minimum=1)
            if model_type.upper() != "QWEN"
            else max_tokens
        )

        # client = self._client_factory(api_key=api_token, base_url=self._base_url(endpoint_url))
        # [20261111]: Disable retries to avoid long delays when the AI service is unresponsive
        client = self._client_factory(
            api_key=api_token,
            base_url=self._base_url(endpoint_url),
            max_retries=0,
        )
        if stream:
            chunks = self._create_chat_completion(
                client,
                model,
                prompt,
                temperature,
                top_p,
                max_tokens,
                max_completion_tokens,
                True,
                timeout,
                model_type,
            )
            content_parts: list[str] = []
            response_id = None
            response_model = model
            usage = None
            finish_reason = None
            for chunk in chunks:
                response_id = getattr(chunk, "id", response_id)
                response_model = getattr(chunk, "model", response_model)
                usage = getattr(chunk, "usage", None) or usage
                if chunk.choices:
                    choice = chunk.choices[0]
                    content_parts.append(choice.delta.content or "")
                    finish_reason = getattr(choice, "finish_reason", finish_reason)
            content = "".join(content_parts)
            self._log_response_metrics(
                started_at, response_id, response_model, usage, content, finish_reason
            )
            if not content.strip():
                raise RuntimeError(
                    "[ERR-19] The OpenAI endpoint returned no text content "
                    f"(finish_reason={finish_reason!s}). Increase "
                    "OFTL_OPENAI_MAX_COMPLETION_TOKENS for GPT models."
                )
            return content
        response = self._create_chat_completion(
            client,
            model,
            prompt,
            temperature,
            top_p,
            max_tokens,
            max_completion_tokens,
            False,
            timeout,
            model_type,
        )

        choice = response.choices[0]
        response_content = choice.message.content
        response_content_text = response_content if isinstance(response_content, str) else ""
        usage = getattr(response, "usage", None)
        self._log_response_metrics(
            started_at,
            getattr(response, "id", None),
            getattr(response, "model", model),
            usage,
            response_content_text,
            getattr(choice, "finish_reason", None),
        )
        if not response_content_text.strip():
            reasoning_tokens = getattr(
                getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None
            )
            raise RuntimeError(
                "[ERR-19] The OpenAI endpoint returned no text content "
                f"(finish_reason={getattr(choice, 'finish_reason', None)!s}, "
                f"reasoning_tokens={reasoning_tokens!s}). Increase "
                "OFTL_OPENAI_MAX_COMPLETION_TOKENS for GPT models."
            )
        return response_content_text

    @staticmethod
    def _create_chat_completion(
        client: OpenAI,
        model: str,
        prompt: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        max_completion_tokens: int,
        stream: bool,
        timeout: int,
        modeltype: str = "QWEN",
    ) -> Any:
        """Call the chat-completions API with the supplied request parameters."""
        if modeltype.upper() == "QWEN":
            Logging.info("Setting model type to QWEN for chat completion")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stream=stream,
                timeout=timeout,
            )
        else:
            Logging.info("Setting model type to GPT for chat completion")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_completion_tokens,
                stream=stream,
                timeout=timeout,
            )
        return response

    @staticmethod
    def _log_response_metrics(
        started_at: float,
        response_id: object,
        model: object,
        usage: object,
        content: str,
        finish_reason: object = None,
    ) -> None:
        """Log response timing, token usage, and key metadata."""
        elapsed_seconds = perf_counter() - started_at
        reasoning_tokens = getattr(
            getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None
        )
        Logging.info(
            "OpenAI response: "
            f"elapsed_seconds={elapsed_seconds:.3f}, "
            f"model={model!s}, response_id={response_id!s}, "
            f"finish_reason={finish_reason!s}, reasoning_tokens={reasoning_tokens!s}, "
            f"prompt_tokens={getattr(usage, 'prompt_tokens', None)!s}, "
            f"completion_tokens={getattr(usage, 'completion_tokens', None)!s}, "
            f"total_tokens={getattr(usage, 'total_tokens', None)!s}, "
            f"response_characters={len(content)}"
        )

    def callJson(self, prompt: str) -> dict[str, object]:
        """Send ``prompt`` and return the JSON response as a dictionary."""
        response = json.loads(self.call(prompt))
        if not isinstance(response, dict):
            raise RuntimeError("[ERR-20] The OpenAI endpoint returned JSON that is not an object")
        return response

    def _required_string(self, key: str) -> str:
        value = self._configuration_getter(key, None)
        if not isinstance(value, str) or not value.strip():
            raise OpenAIConfigurationError(
                f"[ERR-21] Required OpenAI configuration is missing: {key}"
            )
        return value.strip()

    def _model_setting(self) -> str:
        value = self._configuration_getter("OFTL_OPENAI_MODEL", self._DEFAULT_MODEL)
        if not isinstance(value, str) or not value.strip():
            raise OpenAIConfigurationError("OFTL_OPENAI_MODEL must be a non-empty string")
        return value.strip()

    def _float_setting(self, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self._configuration_getter(key, default)
        if not isinstance(value, (str, int, float)):
            raise OpenAIConfigurationError(f"[ERR-22] {key} must be a number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as error:
            raise OpenAIConfigurationError(f"[ERR-22] {key} must be a number") from error
        if not minimum <= parsed <= maximum:
            raise OpenAIConfigurationError(
                f"[ERR-23] {key} must be between {minimum} and {maximum}"
            )
        return parsed

    def _int_setting(self, key: str, default: int, minimum: int) -> int:
        value = self._configuration_getter(key, default)
        if not isinstance(value, (str, int)):
            raise OpenAIConfigurationError(f"[ERR-24] {key} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise OpenAIConfigurationError(f"[ERR-24] {key} must be an integer") from error
        if parsed < minimum:
            raise OpenAIConfigurationError(f"[ERR-25] {key} must be at least {minimum}")
        return parsed

    def _bool_setting(self, key: str, default: bool) -> bool:
        value = self._configuration_getter(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise OpenAIConfigurationError(f"[ERR-26] {key} must be true or false")

    @classmethod
    def _base_url(cls, endpoint_url: str) -> str:
        """Convert a full chat-completions URL to the base URL expected by the SDK."""
        normalized = endpoint_url.rstrip("/")
        if normalized.endswith(cls._CHAT_COMPLETIONS_PATH):
            return normalized[: -len(cls._CHAT_COMPLETIONS_PATH)]
        return normalized
