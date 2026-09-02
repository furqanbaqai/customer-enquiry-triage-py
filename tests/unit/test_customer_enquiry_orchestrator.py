import json
from unittest.mock import MagicMock

import pytest

from src.application.CustomerEnquiryOrchaestrator import CustomerEnquiryOrchestrator


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


def test_parse_enquiry_message_loads_application_schema() -> None:
    enquiry = valid_enquiry()

    parsed = CustomerEnquiryOrchestrator.parse_enquiry_message(json.dumps(enquiry).encode())

    assert parsed == enquiry


def test_parse_enquiry_message_rejects_schema_violation() -> None:
    enquiry = valid_enquiry()
    enquiry.pop("message")

    with pytest.raises(ValueError, match="does not match the request schema"):
        CustomerEnquiryOrchestrator.parse_enquiry_message(json.dumps(enquiry).encode())


def test_process_enquiry_sends_rendered_configured_prompt() -> None:
    enquiry = valid_enquiry()
    prompt_loader = MagicMock()
    prompt_loader.load_configured_prompt.return_value = "rendered prompt"
    assessment = {"emotionalType": "Calm"}
    generated_response = {
        "greeting": "<p>Dear Valued Customer,</p>",
        "body": "<p>Thank you for your inquiry.</p>",
        "closing": "<p>We are here to help.</p>",
        "signature": "Best regards,<br><b>Customer Support Team</b>",
        "infoAvail": False,
    }
    prompt_sender = MagicMock(side_effect=[assessment, generated_response])
    prompt_loader.load_configured_prompt.side_effect = [
        "rendered assessment prompt",
        "rendered response prompt",
    ]
    language_detector = MagicMock(return_value="eng")
    response_message_utility = MagicMock()
    orchestrator = CustomerEnquiryOrchestrator(
        prompt_loader,
        prompt_sender,
        language_detector=language_detector,
        response_message_utility=response_message_utility,
    )

    orchestrator.process_enquiry(json.dumps(enquiry).encode())

    assert prompt_loader.load_configured_prompt.call_args_list == [
        (("OFTL_AI_PROMPT_1", {
            "MESSAGE": enquiry["message"],
            "CATEGORY": enquiry["category"],
        }),),
        (("OFTL_AI_PROMPT_2", {
            "INPUT_MESSAGE": enquiry["message"],
            "INPUT_EMOTION": "Calm",
            "PRODUCT_INFORMATION": enquiry["category"],
        }),),
    ]
    language_detector.assert_called_once_with(enquiry["message"])
    assert prompt_sender.call_args_list == [
        (("rendered assessment prompt",),),
        (("rendered response prompt",),),
    ]
    response_message_utility.send_response_message.assert_called_once_with(
        enquiry, assessment, generated_response, "0000", "Success"
    )
