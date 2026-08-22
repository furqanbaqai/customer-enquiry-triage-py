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
    meta = enquiry["meta"]
    assert isinstance(meta, dict)
    prompt_loader = MagicMock()
    prompt_loader.load_configured_prompt.return_value = "rendered prompt"
    prompt_sender = MagicMock()
    orchestrator = CustomerEnquiryOrchestrator(prompt_loader, prompt_sender)

    orchestrator.process_enquiry(json.dumps(enquiry).encode())

    prompt_loader.load_configured_prompt.assert_called_once_with(
        "OFTL_AI_PROMPT_1",
        {
            "MESSAGE": enquiry["message"],
            "FIRST_NAME": enquiry["firstName"],
            "LAST_NAME": enquiry["lastName"],
            "CHANNEL": meta["channel"],
            "REFERENCE_NUMBER": meta["refNumber"],
        },
    )
    prompt_sender.assert_called_once_with("rendered prompt")
