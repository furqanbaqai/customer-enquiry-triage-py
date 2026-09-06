"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Provides an environment-configured OpenAI-compatible endpoint utility.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import json
from collections.abc import Callable
from time import perf_counter
from typing import Final

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

        client = self._client_factory(api_key=api_token, base_url=self._base_url(endpoint_url))
        if stream:
            chunks = client.chat.completions.create(
                model=self._DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stream=True,
                timeout=timeout,
            )
            content_parts: list[str] = []
            response_id = None
            response_model = self._DEFAULT_MODEL
            usage = None
            for chunk in chunks:
                response_id = getattr(chunk, "id", response_id)
                response_model = getattr(chunk, "model", response_model)
                usage = getattr(chunk, "usage", None) or usage
                if chunk.choices:
                    content_parts.append(chunk.choices[0].delta.content or "")
            content = "".join(content_parts)
            self._log_response_metrics(started_at, response_id, response_model, usage, content)
            return content
        response = client.chat.completions.create(
            model=self._DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=False,
            timeout=timeout,
        )

        response_content = response.choices[0].message.content
        if response_content is None:
            raise RuntimeError("[ERR-19] The OpenAI endpoint returned no text content")
        self._log_response_metrics(
            started_at,
            getattr(response, "id", None),
            getattr(response, "model", self._DEFAULT_MODEL),
            getattr(response, "usage", None),
            response_content,
        )
        return response_content

    @staticmethod
    def _log_response_metrics(
        started_at: float,
        response_id: object,
        model: object,
        usage: object,
        content: str,
    ) -> None:
        """Log response timing, token usage, and key metadata."""
        elapsed_seconds = perf_counter() - started_at
        Logging.info(
            "OpenAI response: "
            f"elapsed_seconds={elapsed_seconds:.3f}, "
            f"model={model!s}, response_id={response_id!s}, "
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
