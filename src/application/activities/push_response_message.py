"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Publishes the completed customer enquiry response through an activity.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
from typing import Any

from temporalio import activity

from src.utilities import ResponseMessageUtility


class PUSHResponseMessage:
    def __init__(self, response_message_utility: ResponseMessageUtility) -> None:
        self._response_message_utility = response_message_utility

    @activity.defn(
        name="Activity for publishing the completed customer enquiry response to the reply queue"
    )
    async def push_response_message(
        self, message: dict[str, Any], errorCode: str = "0000", errorMessage: str = "Success"
    ) -> dict[str, Any]:
        """Publish the enquiry, classification, and generated response to the result queue."""
        activity.logger.info("Response message publishing initiated")
        parsed_message = message["parsed_message"]
        _classification = message["_classification"]
        _ai_response_message = message["_ai_response_message"]
        return await asyncio.to_thread(
            self._response_message_utility.send_response_message,
            parsed_message,
            _classification,
            _ai_response_message,
            errorCode,
            errorMessage,
        )
