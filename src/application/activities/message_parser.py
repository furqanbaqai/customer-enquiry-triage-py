import json
from pathlib import Path

from jsonschema import validate
from temporalio import activity


class RequestMessageParser:
    """Parse and validate enquiry request messages."""

    @activity.defn(name="Parse and validate incoming customer enquiry request message")
    async def parse_request_message(self, request: str) -> dict | None:
        """Return the parsed, schema-valid request, or None on error."""
        try:
            parsed_request = json.loads(request)
            if not isinstance(parsed_request, dict):
                return None

            schema_path = (
                Path(__file__).resolve().parent.parent / "schema" / "enquiry-request-v1.0.json"
            )
            with schema_path.open(encoding="utf-8") as schema_file:
                schema = json.load(schema_file)

            validate(instance=parsed_request, schema=schema)
            return parsed_request
        except Exception as e:
            activity.logger.error(
                "Failed to parse and validate request message (%s)", type(e).__name__
            )
            return None
