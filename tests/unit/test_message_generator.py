import asyncio
from typing import Any, get_type_hints
from unittest.mock import MagicMock

import pytest
from temporalio.converter import DataConverter
from temporalio.testing import ActivityEnvironment

from src.application.activities.message_generator import MessageGenerator


@pytest.mark.parametrize("key", ["OFTL_AI_PROMPT_2", "CUSTOM_RESPONSE_PROMPT"])
def test_generates_emotion_aware_response(key: str) -> None:
    loader = MagicMock()
    loader.load_configured_prompt.return_value = "rendered response prompt"
    response = {"response": "We can help", "details": [None, True, 0.9]}
    sender = MagicMock(return_value=response)
    generator = MessageGenerator(loader, sender, key)
    message: dict[str, Any] = {"message": "Help", "category": "Accounts"}

    async def execute() -> None:
        converter = DataConverter.default
        hints = get_type_hints(MessageGenerator.generate_response_message)
        payloads = await converter.encode([message, "Frustrated"])
        arguments = await converter.decode(payloads, [hints["message"], hints["emotions"]])
        result = await ActivityEnvironment().run(generator.generate_response_message, *arguments)
        assert result is response
        encoded = await converter.encode([result])
        assert await converter.decode(encoded, [hints["return"]]) == [response]

    asyncio.run(execute())
    loader.load_configured_prompt.assert_called_once_with(
        key,
        {"INPUT_MESSAGE": "Help", "INPUT_EMOTION": "Frustrated", "PRODUCT_INFORMATION": "Accounts"},
    )
    sender.assert_called_once_with("rendered response prompt")


@pytest.mark.parametrize("boundary", ["prompt", "ai"])
def test_generation_propagates_failure(boundary: str) -> None:
    loader = MagicMock()
    sender = MagicMock()
    failure = RuntimeError("generation unavailable")
    if boundary == "prompt":
        loader.load_configured_prompt.side_effect = failure
    else:
        sender.side_effect = failure
    generator = MessageGenerator(loader, sender)
    with pytest.raises(RuntimeError, match="generation unavailable") as error:
        asyncio.run(
            ActivityEnvironment().run(
                generator.generate_response_message,
                {"message": "Help", "category": "Accounts"},
                "Calm",
            )
        )
    assert error.value is failure
    if boundary == "prompt":
        sender.assert_not_called()
