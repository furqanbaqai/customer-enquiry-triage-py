"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md
Description: Coordinates the end-to-end processing of incoming customer enquiries.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import json
from collections.abc import Callable
from importlib.resources import files

from jsonschema import ValidationError, validate

from src.utilities import Logging, OpenAIUtility, PromptLoader


class CustomerEnquiryOrchestrator:
    """
    Coordinate the end-to-end processing of an incoming customer enquiry message.
    <br/><br/>Main tasks include:
    - Deserialize and validate the incoming message.
    - Check for duplicate processing using the enquiry/message ID.
    - Invoke the domain classification workflow.
    - Call the AI-classification interface.
    - Persist the enquiry and processing history.
    - Publish the result through an output-queue interface.
    - Coordinate transaction completion or rollback.
    """

    def __init__(
        self,
        prompt_loader: PromptLoader | None = None,
        prompt_sender: Callable[[str], str] | None = None,
        prompt_configuration_key: str = "OFTL_AI_PROMPT_1",
    ) -> None:
        """Create the orchestrator with injectable prompt and AI boundaries."""
        self._prompt_loader = prompt_loader or PromptLoader()
        self._func_OpenaiUtil_callJSON = prompt_sender or OpenAIUtility().callJson
        self._prompt_configuration_key = prompt_configuration_key

    @staticmethod
    def parse_enquiry_message(message: bytes) -> dict[str, object]:
        """Parse and validate an incoming enquiry message."""
        try:
            enquiry = json.loads(message.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("The enquiry message must be valid UTF-8 JSON") from error

        schema_resource = files("src.application").joinpath("schema", "enquiry-request-v1.0.json")
        try:
            with schema_resource.open(encoding="utf-8") as schema_file:
                schema = json.load(schema_file)
            validate(instance=enquiry, schema=schema)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Unable to load the enquiry request schema") from error
        except ValidationError as error:
            raise ValueError("The enquiry message does not match the request schema") from error

        if not isinstance(enquiry, dict):
            raise ValueError("The enquiry message must be a JSON object")
        Logging.info("[CEP] Parsed customer enquiry message successfully.")
        return enquiry

    def process_enquiry(self, message: bytes) -> None:
        """
        Process an incoming customer enquiry message.
        :param message: The raw message bytes received from the input queue.
        """
        try:
            Logging.info(
                "[CEP] Parsing incoming customer enquiry message (%d bytes).", len(message)
            )
            enquiry_message = self.parse_enquiry_message(message)
            Logging.info("[CEP] Loading from %s.", self._prompt_configuration_key)
            prompt = self._generate_prompt(enquiry_message, self._prompt_configuration_key)

            Logging.info("[CEP] Customer enquiry submitted for AI classification.")
            result = self._func_OpenaiUtil_callJSON(prompt)
            Logging.info("[CEP] AI classification completed successfully.")
            Logging.debug("[CEP] AI classification result: %s", json.dumps(result))

        except ValidationError as error:
            raise ValueError("The enquiry message does not match the request schema") from error
        except ValueError:
            # Preserve the specific validation error raised while parsing.
            raise
        except Exception as error:
            raise RuntimeError(
                "An unexpected error occurred while processing the enquiry: %s", str(error)
            ) from error

    def _generate_prompt(self, enquiry: dict[str, object], promptConfigKey: str) -> str:
        """Generate a prompt for AI classification based on the enquiry data."""
        meta = enquiry["meta"]
        if not isinstance(meta, dict):
            raise ValueError("The enquiry metadata must be a JSON object")
        prompt_variables = {
            "MESSAGE": enquiry["message"],
            "FIRST_NAME": enquiry["firstName"],
            "LAST_NAME": enquiry["lastName"],
            "CHANNEL": meta["channel"],
            "REFERENCE_NUMBER": meta["refNumber"],
        }
        return self._prompt_loader.load_configured_prompt(promptConfigKey, prompt_variables)
