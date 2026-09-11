"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Tests enquiry validation and Temporal submission without external services.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio.common import WorkflowIDReusePolicy

from src.application.CustomerEnquiryClient import CustomerEnquiryClient
from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator
from src.config import ConfigLoader
from src.utilities import Logging

client_module = importlib.import_module("src.application.CustomerEnquiryClient")


@pytest.fixture
def enquiry() -> dict[str, object]:
    return {
        "meta": {
            "refNumber": "REF-123",
            "channel": "WebSite",
            "reqIssuedAt": "2026-08-19T10:00:00Z",
        },
        "mobileNumber": "+971501234567",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "emailAddress": "ada@example.com",
        "message": "Please help with my enquiry. مرحبا",
        "category": "Retail Accounts",
        "receivedAt": "2026-08-19T10:01:00Z",
    }


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfigLoader, "configurations", {"OFTL_LOG_LEVEL": "INFO"})
    monkeypatch.setattr(Logging, "_configured", True)


@pytest.fixture
def connect(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    connection = AsyncMock(return_value=MagicMock(start_workflow=AsyncMock()))
    monkeypatch.setattr(client_module.Client, "connect", connection)
    return connection


@pytest.mark.parametrize("endpoint", [None, "temporal.example:7233"])
def test_submits_validated_enquiry(
    enquiry: dict[str, object], connect: AsyncMock, endpoint: str | None
) -> None:
    if endpoint is not None:
        ConfigLoader.configurations["OFTL_AI_TEMPORALURL"] = endpoint

    CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())

    connect.assert_awaited_once_with(endpoint or "localhost:7233")
    execute = connect.return_value.start_workflow
    execute.assert_awaited_once()
    arguments = execute.await_args
    assert arguments.args[0] is CustomerEnquiryOrchaestrator.run
    assert json.loads(arguments.args[1]) == enquiry
    assert arguments.kwargs["id"] == "CE-WEBSITE-REF-123"
    assert arguments.kwargs["task_queue"] == "CUSTOMER.ENQUIRY.REQUEST"
    assert arguments.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
    assert arguments.kwargs["execution_timeout"].total_seconds() == 1500
    assert arguments.kwargs["rpc_timeout"].total_seconds() == 60
    assert arguments.kwargs["task_timeout"].total_seconds() == 10
    execute.return_value.result.assert_not_called()


@pytest.mark.parametrize("payload", [b"\xff", b"{", b"{}", b"[]", b"null"])
def test_rejects_invalid_input(payload: bytes, connect: AsyncMock) -> None:
    with pytest.raises(ValueError):
        CustomerEnquiryClient.sendToWorkflow(payload)
    connect.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [("emailAddress", "invalid"), ("receivedAt", "yesterday"), ("message", "")],
)
def test_enforces_schema_formats(
    enquiry: dict[str, object], connect: AsyncMock, field: str, value: str
) -> None:
    enquiry[field] = value
    with pytest.raises(ValueError, match="schema validation"):
        CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    connect.assert_not_awaited()


def test_schema_load_failure(
    enquiry: dict[str, object], connect: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "_SCHEMA_PATH", Path("missing-enquiry-schema.json"))
    with pytest.raises(RuntimeError, match="load.*schema") as error:
        CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    assert isinstance(error.value.__cause__, FileNotFoundError)
    connect.assert_not_awaited()


@pytest.mark.parametrize("stage", ["connect", "start"])
@pytest.mark.parametrize("failure_type", [RuntimeError, TimeoutError])
def test_temporal_failure_preserves_cause_without_logging_payload(
    enquiry: dict[str, object],
    connect: AsyncMock,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    failure_type: type[Exception],
) -> None:
    failure = failure_type("private customer data")
    if stage == "connect":
        connect.side_effect = failure
    else:
        connect.return_value.start_workflow.side_effect = failure
    with pytest.raises(RuntimeError, match="Temporal enquiry execution failed") as error:
        CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    assert error.value.__cause__ is failure
    assert "private customer data" not in caplog.text
    assert str(enquiry["message"]) not in caplog.text


def test_rejects_empty_endpoint(enquiry: dict[str, object], connect: AsyncMock) -> None:
    ConfigLoader.configurations["OFTL_AI_TEMPORALURL"] = " "
    with pytest.raises(ValueError, match="OFTL_AI_TEMPORALURL"):
        CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    connect.assert_not_awaited()


def test_rejects_active_event_loop(enquiry: dict[str, object], connect: AsyncMock) -> None:
    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="active asyncio event loop"):
            CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())

    asyncio.run(invoke())
    connect.assert_not_awaited()


def test_workflow_timeout_reserves_error_publication_budget(
    enquiry: dict[str, object], connect: AsyncMock
) -> None:
    CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    timeout = connect.return_value.start_workflow.call_args.kwargs["execution_timeout"]
    assert timeout.total_seconds() == 25 * 60


@pytest.mark.parametrize("policy", list(WorkflowIDReusePolicy))
def test_configured_reuse_policy(
    enquiry: dict[str, object], connect: AsyncMock, policy: WorkflowIDReusePolicy
) -> None:
    ConfigLoader.configurations["OFTL_AI_TEMPORALREUSE_POLICY"] = f" {policy.name.lower()} "
    CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    assert connect.return_value.start_workflow.call_args.kwargs["id_reuse_policy"] == policy


@pytest.mark.parametrize("policy", ["", " ", "UNKNOWN"])
def test_rejects_unknown_reuse_policy(
    enquiry: dict[str, object], connect: AsyncMock, policy: str
) -> None:
    ConfigLoader.configurations["OFTL_AI_TEMPORALREUSE_POLICY"] = policy
    with pytest.raises(ValueError, match="OFTL_AI_TEMPORALREUSE_POLICY"):
        CustomerEnquiryClient.sendToWorkflow(json.dumps(enquiry).encode())
    connect.assert_not_awaited()
