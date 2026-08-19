import json

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
