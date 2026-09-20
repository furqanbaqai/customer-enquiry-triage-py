"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Tests active request parsing and the Temporal processing pipeline.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from src.application.activities.message_parser import RequestMessageParser
from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator


def valid_enquiry() -> dict[str, object]:
    return {
        "meta": {
            "refNumber": "REF-123",
            "channel": "WebSite",
            "reqIssuedAt": "2026-08-19T10:00:00Z",
        },
        "mobileNumber": "+971 50 123 4567",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "emailAddress": "ada@example.com",
        "message": "Please help with my enquiry.",
        "category": "Retail Accounts",
        "receivedAt": "2026-08-19T10:01:00Z",
    }


def test_parser_loads_application_schema() -> None:
    enquiry = valid_enquiry()
    parsed = asyncio.run(
        ActivityEnvironment().run(RequestMessageParser().parse_request_message, json.dumps(enquiry))
    )
    assert parsed == enquiry


def test_parser_rejects_missing_required_field() -> None:
    enquiry = valid_enquiry()
    enquiry.pop("message")
    with pytest.raises(ApplicationError, match="Request validation failed") as error:
        asyncio.run(
            ActivityEnvironment().run(
                RequestMessageParser().parse_request_message, json.dumps(enquiry)
            )
        )
    assert error.value.non_retryable


def test_workflow_activity_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    enquiry = valid_enquiry()
    parser = AsyncMock(return_value=enquiry)
    activities = AsyncMock(
        side_effect=[
            {"emotionalType": "Calm", "product_code": "SIB-RET-001"},
            {"response": "We can help"},
            {"meta": {"responseCode": "0000"}},
        ]
    )
    monkeypatch.setattr(workflow, "logger", MagicMock())
    monkeypatch.setattr(workflow, "execute_activity", parser)
    monkeypatch.setattr(workflow, "execute_activity_method", activities)
    result = asyncio.run(CustomerEnquiryOrchaestrator().run(json.dumps(enquiry)))
    assert result == {"meta": {"responseCode": "0000"}}
    calls = [parser.await_args, *activities.await_args_list]
    for call, attempt, total in zip(calls, [30, 300, 300, 30], [120, 540, 540, 180], strict=True):
        assert call.kwargs["start_to_close_timeout"].total_seconds() == attempt
        assert call.kwargs["schedule_to_close_timeout"].total_seconds() == total
        policy = call.kwargs["retry_policy"]
        assert policy.maximum_attempts == 5
        assert policy.initial_interval.total_seconds() == 2
        assert policy.maximum_interval.total_seconds() == 10
    assert activities.await_args_list[1].kwargs["args"] == [
        enquiry["message"],
        "SIB-RET-001",
        "Calm",
    ]
