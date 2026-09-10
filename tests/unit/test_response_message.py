"""Unit tests for generating and sending customer enquiry response messages."""

from unittest.mock import MagicMock

import pytest

from src.utilities import ResponseMessageUtility


def original_message() -> dict[str, object]:
    return {
        "meta": {
            "refNumber": "REF-123",
            "channel": "WebSite",
            "reqIssuedAt": "2026-08-19T10:00:00Z",
        },
        "message": "Please help with my enquiry.",
        "category": "Retail Accounts",
    }


def test_generates_and_sends_complete_response_without_mutating_inputs() -> None:
    request = original_message()
    assessment = {"type": "Enquiry", "confidence": 0.95}
    generated = {"lang": "eng", "shortMessage": "We can help."}
    expected_request = request.copy()
    sender = MagicMock()
    utility = ResponseMessageUtility(sender)

    response = utility.send_response_message(request, assessment, generated, "00", "Success")

    assert response == {
        "meta": {
            "refNumber": "REF-123",
            "channel": "WebSite",
            "reqIssuedAt": "2026-08-19T10:00:00Z",
            "responseCode": "00",
            "responseDescription": "Success",
        },
        "orignalMessage": {
            "message": "Please help with my enquiry.",
            "category": "Retail Accounts",
        },
        "aiAssesment": assessment,
        "aiGeneratedResponse": generated,
    }
    assert request == expected_request
    sender.put_result_message.assert_called_once_with(response)


def test_omits_none_aggregates() -> None:
    response = ResponseMessageUtility.generate_response_message(
        None, None, None, "99", "Unable to process"
    )

    assert response == {"meta": {"responseCode": "99", "responseDescription": "Unable to process"}}


def test_omits_only_optional_none_aggregates() -> None:
    response = ResponseMessageUtility.generate_response_message(
        original_message(), None, None, "00", "Success"
    )

    assert "meta" in response
    assert "orignalMessage" in response
    assert "aiAssesment" not in response
    assert "aiGeneratedResponse" not in response


def test_rejects_original_message_without_dictionary_metadata() -> None:
    with pytest.raises(ValueError, match=r"\[ERR-37\]"):
        ResponseMessageUtility.generate_response_message({}, {}, {}, "00", "Success")
