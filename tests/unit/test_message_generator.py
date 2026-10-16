import asyncio
import json
from pathlib import Path
from typing import get_type_hints
from unittest.mock import MagicMock, mock_open

import pytest
from temporalio.converter import DataConverter
from temporalio.testing import ActivityEnvironment

from src.application.activities.message_generator import MessageGenerator
from src.config import ConfigLoader


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfigLoader, "configurations", {"TEST": "1"})


@pytest.mark.parametrize("catalogue", [None, "", "custom/product catalogue"])
def test_product_catalogue_folder(catalogue: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if catalogue is not None:
        monkeypatch.setitem(ConfigLoader.configurations, "OFTL_AI_PRODUCTCAT", catalogue)
    opened_paths: list[Path] = []
    product_open = mock_open(read_data="{}")

    def open_product(path: Path, *, encoding: str) -> object:
        opened_paths.append(path)
        return product_open(encoding=encoding)

    monkeypatch.setattr(Path, "open", open_product)
    generator = MessageGenerator(MagicMock(), MagicMock(return_value={}))
    generator._getAIResponseMessage("Help", "SIB-RET-001", "Calm")
    expected_folder = (
        Path(catalogue)
        if catalogue
        else Path(__file__).resolve().parents[2] / "prompts" / "product_json"
    )
    assert opened_paths == [expected_folder / "SIB-RET-001.json"]


@pytest.mark.parametrize("key", ["OFTL_AI_PROMPT_2", "CUSTOM_RESPONSE_PROMPT"])
def test_generates_emotion_aware_response(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    loader = MagicMock()
    loader.load_configured_prompt.return_value = "rendered response prompt"
    response = {"response": "We can help", "details": [None, True, 0.9]}
    sender = MagicMock(return_value=response)
    generator = MessageGenerator(loader, sender, key)
    product = {"product_code": "SIB-RET-001", "name": "Example account"}
    product_open = mock_open(read_data=json.dumps(product))
    monkeypatch.setattr(Path, "open", product_open)

    async def execute() -> None:
        converter = DataConverter.default
        hints = get_type_hints(MessageGenerator.generate_response_message)
        payloads = await converter.encode(["Help", "SIB-RET-001", "Frustrated"])
        arguments = await converter.decode(
            payloads, [hints["message"], hints["product_code"], hints["emotions"]]
        )
        result = await ActivityEnvironment().run(generator.generate_response_message, *arguments)
        assert result is response
        encoded = await converter.encode([result])
        assert await converter.decode(encoded, [hints["return"]]) == [response]

    asyncio.run(execute())
    loader.load_configured_prompt.assert_called_once_with(
        key,
        {
            "INPUT_MESSAGE": "Help",
            "INPUT_EMOTION": "Frustrated",
            "PRODUCT_INFORMATION": json.dumps(product),
        },
    )
    sender.assert_called_once_with("rendered response prompt")
    product_open.assert_called_once_with(encoding="utf-8")


@pytest.mark.parametrize("boundary", ["prompt", "ai"])
def test_generation_propagates_failure(boundary: str, monkeypatch: pytest.MonkeyPatch) -> None:
    loader = MagicMock()
    sender = MagicMock()
    monkeypatch.setattr(Path, "open", mock_open(read_data="{}"))
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
                "Help",
                "SIB-RET-001",
                "Calm",
            )
        )
    assert error.value is failure
    if boundary == "prompt":
        sender.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError("Missing product"), json.JSONDecodeError("Invalid product", "{", 1)],
)
def test_product_load_failure_prevents_ai_call(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(Path, "open", MagicMock(side_effect=failure))
    loader, sender = MagicMock(), MagicMock()
    generator = MessageGenerator(loader, sender)
    with pytest.raises(type(failure)) as error:
        asyncio.run(
            ActivityEnvironment().run(
                generator.generate_response_message, "Help", "SIB-RET-001", "Calm"
            )
        )
    assert error.value is failure
    loader.load_configured_prompt.assert_not_called()
    sender.assert_not_called()
