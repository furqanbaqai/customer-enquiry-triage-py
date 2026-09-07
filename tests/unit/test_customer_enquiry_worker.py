"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Verifies Temporal worker registration, lifecycle, and failure handling.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio import workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from src.application.activities.message_classifier import MessageClassifier
from src.application.activities.message_generator import MessageGenerator
from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator
from src.application.CustomerEnquiryWorker import CustomerEnquiryWorker
from src.config import ConfigLoader
from src.utilities import Logging

worker_module = importlib.import_module("src.application.CustomerEnquiryWorker")


def test_workflow_loads_in_temporal_sandbox() -> None:
    async def prepare() -> None:
        SandboxedWorkflowRunner().prepare_workflow(
            workflow._Definition.must_from_class(CustomerEnquiryOrchaestrator)
        )

    asyncio.run(prepare())


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfigLoader, "configurations", {"OFTL_LOG_LEVEL": "INFO"})
    monkeypatch.setattr(Logging, "_configured", True)


@pytest.mark.parametrize("endpoint", [None, " temporal.example:7233 "])
def test_registers_workflow_and_bound_activities_and_shuts_down(
    monkeypatch: pytest.MonkeyPatch, endpoint: str | None
) -> None:
    if endpoint is not None:
        ConfigLoader.configurations["OFTL_AI_TEMPORALURL"] = endpoint
    connect = AsyncMock()
    context = AsyncMock()
    context.__aexit__.return_value = False
    factory = MagicMock(return_value=context)
    wait = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker_module.Client, "connect", connect)
    monkeypatch.setattr(worker_module, "Worker", factory)
    monkeypatch.setattr(
        worker_module.asyncio, "Event", MagicMock(return_value=MagicMock(wait=wait))
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(CustomerEnquiryWorker.start())

    connect.assert_awaited_once_with(endpoint.strip() if endpoint else "localhost:7233")
    factory.assert_called_once()
    arguments = factory.call_args
    assert arguments.args == (connect.return_value,)
    assert arguments.kwargs["task_queue"] == "CUSTOMER.ENQUIRY.REQUEST"
    assert arguments.kwargs["workflows"] == [CustomerEnquiryOrchaestrator]
    classifier, generator = arguments.kwargs["activities"]
    assert isinstance(classifier.__self__, MessageClassifier)
    assert classifier.__func__ is MessageClassifier.classify_message
    assert isinstance(generator.__self__, MessageGenerator)
    assert generator.__func__ is MessageGenerator.generate_response_message
    assert arguments.kwargs["graceful_shutdown_timeout"].total_seconds() == 30
    context.__aenter__.assert_awaited_once()
    context.__aexit__.assert_awaited_once()
    assert context.__aexit__.await_args.args[0] is asyncio.CancelledError


def test_rejects_blank_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    ConfigLoader.configurations["OFTL_AI_TEMPORALURL"] = " "
    connect = AsyncMock()
    monkeypatch.setattr(worker_module.Client, "connect", connect)
    with pytest.raises(ValueError, match="OFTL_AI_TEMPORALURL"):
        asyncio.run(CustomerEnquiryWorker.start())
    connect.assert_not_awaited()


@pytest.mark.parametrize("failure_type", [RuntimeError, TimeoutError])
def test_connection_failure_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_type: type[Exception],
) -> None:
    failure = failure_type("private connection details")
    monkeypatch.setattr(worker_module.Client, "connect", AsyncMock(side_effect=failure))
    factory = MagicMock()
    monkeypatch.setattr(worker_module, "Worker", factory)
    with pytest.raises(RuntimeError, match="worker failed") as error:
        asyncio.run(CustomerEnquiryWorker.start())
    assert error.value.__cause__ is failure
    assert "private connection details" not in caplog.text
    factory.assert_not_called()


def test_worker_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("worker failed internally")
    context = AsyncMock()
    context.__aenter__.side_effect = failure
    monkeypatch.setattr(worker_module.Client, "connect", AsyncMock())
    monkeypatch.setattr(worker_module, "Worker", MagicMock(return_value=context))
    with pytest.raises(RuntimeError, match="worker failed") as error:
        asyncio.run(CustomerEnquiryWorker.start())
    assert error.value.__cause__ is failure
