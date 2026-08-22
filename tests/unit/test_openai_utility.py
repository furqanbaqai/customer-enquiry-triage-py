from unittest.mock import MagicMock

import pytest

from src.utilities import OpenAIConfigurationError, OpenAIUtility


def test_call_uses_environment_defaults_with_openai_sdk() -> None:
    configuration = {
        "OFTL_OPENAI_URL": "https://example.com/v1/chat/completions",
        "OFTL_OPENAI_APITOKEN": "secret-token",
    }
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = "classification"
    client_factory = MagicMock(return_value=client)
    utility = OpenAIUtility(configuration.get, client_factory)

    result = utility.call("Classify this enquiry")

    assert result == "classification"
    client_factory.assert_called_once_with(
        api_key="secret-token", base_url="https://example.com/v1"
    )
    client.chat.completions.create.assert_called_once_with(
        model="default",
        messages=[{"role": "user", "content": "Classify this enquiry"}],
        temperature=0.1,
        top_p=0.9,
        max_tokens=200,
        stream=False,
    )


def test_call_loads_overridden_sdk_parameters() -> None:
    configuration = {
        "OFTL_OPENAI_URL": "https://example.com/v1",
        "OFTL_OPENAI_APITOKEN": "secret-token",
        "OFTL_OPENAI_TEMPERATURE": "0.4",
        "OFTL_OPENAI_TOP_P": "0.7",
        "OFTL_OPENAI_MAX_TOKENS": "500",
        "OFTL_OPENAI_STREAM": "false",
    }
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = "classification"
    utility = OpenAIUtility(configuration.get, MagicMock(return_value=client))

    utility.call("Classify this enquiry")

    assert client.chat.completions.create.call_args.kwargs["temperature"] == 0.4
    assert client.chat.completions.create.call_args.kwargs["top_p"] == 0.7
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 500
    assert client.chat.completions.create.call_args.kwargs["stream"] is False


def test_call_requires_endpoint_and_token() -> None:
    utility = OpenAIUtility({}.get, MagicMock())

    with pytest.raises(OpenAIConfigurationError, match="OFTL_OPENAI_URL"):
        utility.call("Classify this enquiry")
