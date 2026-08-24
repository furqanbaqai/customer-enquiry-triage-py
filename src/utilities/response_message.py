"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Builds customer enquiry response envelopes and sends them to IBM MQ.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

from collections.abc import Mapping
from typing import Protocol


class ResultMessageSender(Protocol):
    """Boundary for sending a generated response to the configured result queue."""

    def put_result_message(self, message: dict[str, object]) -> None:
        """Put one response message on the result queue."""
        ...


class ResponseMessageUtility:
    """Generate and send customer enquiry response messages."""

    def __init__(self, message_sender: ResultMessageSender) -> None:
        self._message_sender = message_sender

    @staticmethod
    def generate_response_message(
        original_message: Mapping[str, object] | None,
        ai_assesment: Mapping[str, object] | None,
        ai_generated_response: Mapping[str, object] | None,
        response_code: str,
        response_description: str,
    ) -> dict[str, object]:
        """Build a response envelope without modifying any supplied dictionary."""
        if not isinstance(response_code, str):
            raise TypeError("[ERR-35] The response code must be a string")
        if not isinstance(response_description, str):
            raise TypeError("[ERR-36] The response description must be a string")

        response: dict[str, object] = {}
        if original_message is not None:
            original_copy = dict(original_message)
            meta = original_copy.pop("meta", None)
            if not isinstance(meta, Mapping):
                raise ValueError("[ERR-37] The original message metadata must be a dictionary")
            response["meta"] = {
                **meta,
                "responseCode": response_code,
                "responseDescription": response_description,
            }
            response["orignalMessage"] = original_copy

        if ai_assesment is not None:
            response["aiAssesment"] = dict(ai_assesment)
        if ai_generated_response is not None:
            response["aiGeneratedResponse"] = dict(ai_generated_response)
        return response

    def send_response_message(
        self,
        original_message: Mapping[str, object] | None,
        ai_assesment: Mapping[str, object] | None,
        ai_generated_response: Mapping[str, object] | None,
        response_code: str,
        response_description: str,
    ) -> dict[str, object]:
        """Generate a response, put it on IBM MQ, and return the generated envelope."""
        response = self.generate_response_message(
            original_message,
            ai_assesment,
            ai_generated_response,
            response_code,
            response_description,
        )
        self._message_sender.put_result_message(response)
        return response
