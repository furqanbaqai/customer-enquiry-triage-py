import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
from temporalio import activity
from temporalio.exceptions import ApplicationError


class RequestMessageParser:
    """Parse and validate enquiry request messages."""

    @activity.defn(name="Parse and validate incoming customer enquiry request message")
    async def parse_request_message(self, request: str) -> dict[str, Any]:
        """Reject invalid input without retrying; propagate infrastructure failures for retry."""
        try:
            parsed_request = json.loads(request)
        except json.JSONDecodeError as error:
            raise ApplicationError(
                "Request must be valid JSON", type="InvalidRequest", non_retryable=True
            ) from error
        if not isinstance(parsed_request, dict):
            raise ApplicationError(
                "Request must be a JSON object", type="InvalidRequest", non_retryable=True
            )

        schema_path = (
            Path(__file__).resolve().parent.parent / "schema" / "enquiry-request-v1.0.json"
        )
        with schema_path.open(encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
        try:
            validate(instance=parsed_request, schema=schema)
        except ValidationError as error:
            raise ApplicationError(
                "Request validation failed", type="InvalidRequest", non_retryable=True
            ) from error
        return parsed_request
