"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Tests terminal enquiry failures and error response publication.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError, RetryState
from temporalio.testing import ActivityEnvironment

from src.application.activities.message_parser import RequestMessageParser
from src.application.activities.push_response_message import PUSHResponseMessage
from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator
from src.utilities import ResponseMessageUtility


def activity_failure(state: RetryState) -> ActivityError:
    return ActivityError(
        "Activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test-worker",
        activity_type="test-activity",
        activity_id="test-activity",
        retry_state=state,
    )


@pytest.mark.parametrize(
    "stage,code", [("parsing", "8100"), ("classification", "8200"), ("generation", "8300")]
)
@pytest.mark.parametrize(
    "state",
    [RetryState.MAXIMUM_ATTEMPTS_REACHED, RetryState.NON_RETRYABLE_FAILURE, RetryState.TIMEOUT],
)
def test_terminal_activity_failure_publishes_partial_results(
    monkeypatch: pytest.MonkeyPatch, stage: str, code: str, state: RetryState
) -> None:
    original = {"meta": {"refNumber": "ENQ-1"}, "message": "Help"}
    assessment = {"emotionalType": "Calm"}
    failure = activity_failure(state)
    parser = AsyncMock(return_value=original)
    results: list[object] = [failure, {}]
    if stage == "parsing":
        parser.side_effect = failure
        results = [{}]
    elif stage == "generation":
        results = [assessment, failure, {}]
    activities = AsyncMock(side_effect=results)
    monkeypatch.setattr(workflow, "execute_activity", parser)
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(CustomerEnquiryOrchaestrator().run(json.dumps(original)))
    assert error.value.non_retryable
    assert error.value.__cause__ is failure
    assert error.value.details == (code,)
    published = activities.call_args
    assert published.args[0] is PUSHResponseMessage.push_response_message
    payload, response_code, description = published.kwargs["args"]
    assert payload == {
        "parsed_message": original,
        "_classification": assessment if stage == "generation" else None,
        "_ai_response_message": None,
    }
    assert response_code == code
    assert description
    assert published.kwargs["schedule_to_close_timeout"].total_seconds() == 180
    assert published.kwargs["retry_policy"].maximum_attempts == 5


@pytest.mark.parametrize("assessment", [{}, {"emotionalType": 123}, None])
def test_workflow_validation_error_is_published(
    monkeypatch: pytest.MonkeyPatch, assessment: object
) -> None:
    monkeypatch.setattr(workflow, "execute_activity", AsyncMock(return_value={"meta": {}}))
    activities = AsyncMock(side_effect=[assessment, {}])
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(CustomerEnquiryOrchaestrator().run("{}"))
    assert error.value.details == ("9999",)
    assert activities.call_args.kwargs["args"][1:] == ["9999", "Unable to process the enquiry"]


@pytest.mark.parametrize("processing_fails", [False, True])
def test_publication_failure_does_not_publish_again(
    monkeypatch: pytest.MonkeyPatch, processing_fails: bool
) -> None:
    monkeypatch.setattr(workflow, "execute_activity", AsyncMock(return_value={"meta": {}}))
    failure = activity_failure(RetryState.MAXIMUM_ATTEMPTS_REACHED)
    results: list[object] = (
        [ValueError("private failure"), failure]
        if processing_fails
        else [{"emotionalType": "Calm"}, {"response": "Help"}, failure]
    )
    activities = AsyncMock(side_effect=results)
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    with pytest.raises(ActivityError) as error:
        asyncio.run(CustomerEnquiryOrchaestrator().run("{}"))
    assert error.value is failure
    assert (
        sum(
            call.args[0] is PUSHResponseMessage.push_response_message
            for call in activities.await_args_list
        )
        == 1
    )


@pytest.mark.parametrize("wrapped", [False, True])
def test_cancellation_does_not_publish(monkeypatch: pytest.MonkeyPatch, wrapped: bool) -> None:
    cancellation: BaseException = asyncio.CancelledError()
    if wrapped:
        cancellation = activity_failure(RetryState.CANCEL_REQUESTED)
        cancellation.__cause__ = CancelledError("Cancelled")
    monkeypatch.setattr(workflow, "execute_activity", AsyncMock(side_effect=cancellation))
    activities = AsyncMock()
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    with pytest.raises(type(cancellation)):
        asyncio.run(CustomerEnquiryOrchaestrator().run("{}"))
    activities.assert_not_awaited()


@pytest.mark.parametrize("raw_message", ["invalid JSON", "[]", "{}", '{"meta": 42}'])
def test_parser_rejects_invalid_requests_without_retry(raw_message: str) -> None:
    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            ActivityEnvironment().run(RequestMessageParser().parse_request_message, raw_message)
        )
    assert error.value.non_retryable
    assert error.value.type == "InvalidRequest"


def test_parser_propagates_schema_io_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "open", MagicMock(side_effect=OSError("schema unavailable")))
    with pytest.raises(OSError):
        asyncio.run(ActivityEnvironment().run(RequestMessageParser().parse_request_message, "{}"))


@pytest.mark.parametrize("original", [None, {}, {"meta": 42, "message": "Help"}])
def test_publisher_sends_error_without_valid_metadata(original: dict[str, object] | None) -> None:
    sender = MagicMock()
    publisher = PUSHResponseMessage(ResponseMessageUtility(sender))
    payload = {"parsed_message": original, "_classification": None, "_ai_response_message": None}
    result = asyncio.run(
        ActivityEnvironment().run(
            publisher.push_response_message, payload, "8100", "Request validation failed"
        )
    )
    assert result["meta"] == {
        "responseCode": "8100",
        "responseDescription": "Request validation failed",
    }
    if original is not None:
        assert result["orignalMessage"] == original
    sender.put_result_message.assert_called_once_with(result)


@pytest.fixture(autouse=True)
def isolate_workflow_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "logger", MagicMock())


@pytest.mark.parametrize("raw_message", ["invalid JSON", "[]"])
def test_undecodable_request_publishes_error_without_original(
    monkeypatch: pytest.MonkeyPatch, raw_message: str
) -> None:
    failure = activity_failure(RetryState.NON_RETRYABLE_FAILURE)
    monkeypatch.setattr(workflow, "execute_activity", AsyncMock(side_effect=failure))
    activities = AsyncMock(return_value={})
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    with pytest.raises(ApplicationError):
        asyncio.run(CustomerEnquiryOrchaestrator().run(raw_message))
    payload, code, _ = activities.call_args.kwargs["args"]
    assert payload["parsed_message"] is None
    assert code == "8100"
