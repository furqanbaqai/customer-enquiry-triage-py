"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md
Description: Coordinates the end-to-end processing of incoming customer enquiries.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import json
import traceback
from collections.abc import Callable
from importlib.resources import files

from jsonschema import ValidationError, validate

from src.utilities import (
    LanguageValidator,
    Logging,
    OpenAIUtility,
    PromptLoader,
    ResponseMessageUtility,
)


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
        prompt_sender: Callable[[str], dict[str, object]] | None = None,
        prompt_configuration_key: str = "OFTL_AI_PROMPT_1",
        language_detector: Callable[[str], str] = LanguageValidator.detect_language,
        response_message_utility: ResponseMessageUtility | None = None,
    ) -> None:
        """Create the orchestrator with injectable prompt and AI boundaries."""
        self._prompt_loader = prompt_loader or PromptLoader()
        self._func_OpenaiUtil_callJSON = prompt_sender or OpenAIUtility().callJson
        self._prompt_configuration_key = prompt_configuration_key
        self._language_detector = language_detector
        self._response_message_utility = response_message_utility

    @staticmethod
    def parse_enquiry_message(message: bytes) -> dict[str, object]:
        """Parse and validate an incoming enquiry message."""
        try:
            enquiry = json.loads(message.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("[ERR-03] The enquiry message must be valid UTF-8 JSON") from error

        schema_resource = files("src.application").joinpath("schema", "enquiry-request-v1.0.json")
        try:
            with schema_resource.open(encoding="utf-8") as schema_file:
                schema = json.load(schema_file)
            validate(instance=enquiry, schema=schema)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("[ERR-04] Unable to load the enquiry request schema") from error
        except ValidationError as error:
            raise ValueError(
                "[ERR-05] The enquiry message does not match the request schema"
            ) from error

        if not isinstance(enquiry, dict):
            raise ValueError("[ERR-06] The enquiry message must be a JSON object")
        Logging.info("[CEP] Parsed customer enquiry message successfully.")
        return enquiry

    def process_enquiry(self, message: bytes) -> None:
        """
        Process an incoming customer enquiry message.
        :param message: The raw message bytes received from the input queue.
        """
        _errHandled = False
        try:
            Logging.info(
                "[CEP] Parsing incoming customer enquiry message (%d bytes).", len(message)
            )
            enquiry_message = self.parse_enquiry_message(message)

            enquiry_text = enquiry_message["message"]
            if not isinstance(enquiry_text, str):
                raise ValueError("[ERR-07] The enquiry message text must be a string")
            language_code = self._language_detector(enquiry_text).upper()
            Logging.info("[CEP] Detected customer enquiry language: %s", language_code)

            Logging.info("[CEP] Loading Prompt from %s.", self._prompt_configuration_key)
            prompt = self._generate_prompt(enquiry_message, self._prompt_configuration_key)

            Logging.info("[CEP] Customer enquiry submitted for AI classification.")
            resp_aiAss = self._func_OpenaiUtil_callJSON(prompt)
            Logging.info("[CEP] AI classification completed successfully.")
            Logging.debug("[CEP] AI classification result: %s", json.dumps(resp_aiAss))

            if self._response_message_utility is None:
                raise RuntimeError("[ERR-39] The response message utility is not configured")
            self._response_message_utility.send_response_message(
                enquiry_message,
                resp_aiAss,
                None,
                "0000",
                "Success",
            )
            Logging.info("[CEP] Message sent to result queue successfully.")
            Logging.info("[CEP] Message Processing completed.")
            Logging.info("[CEP] Waiting for other message..")
        except ValidationError as error:
            self._response_message_utility.send_response_message(
                enquiry_message,
                None,
                None,
                "8100",
                "[ERR-05] The enquiry message does not match the request schema",
            )
            _errHandled = True
            raise ValueError(
                "[ERR-05] The enquiry message does not match the request schema"
            ) from error
        except ValueError:
            # Preserve the specific validation error raised while parsing.
            self._response_message_utility.send_response_message(
                enquiry_message,
                None,
                None,
                "8101",
                "[ERR-05] Value Error occurred while processing the enquiry message",
            )
            _errHandled = True
            raise
        except Exception as error:
            exception_type = type(error).__name__
            stack_trace = traceback.format_exc()
            Logging.error(
                "[CEP] Unexpected error while processing enquiry "
                "(type=%s, message=%s). Stack trace:\n%s",
                exception_type,
                str(error),
                stack_trace,
            )
            if not _errHandled:
                self._response_message_utility.send_response_message(
                    enquiry_message,
                    None,
                    None,
                    "9999",
                    "[ERR-08] An unexpected error occurred while processing the enquiry",
                )
            raise RuntimeError(
                "[ERR-08] An unexpected error occurred while processing the enquiry "
                f"({exception_type}): {str(error)}"
            ) from error

    def _generate_prompt(self, enquiry: dict[str, object], promptConfigKey: str) -> str:
        """Generate a prompt for AI classification based on the enquiry data."""
        meta = enquiry["meta"]
        if not isinstance(meta, dict):
            raise ValueError("[ERR-09] The enquiry metadata must be a JSON object")
        prompt_variables = {"MESSAGE": enquiry["message"], "CATEGORY": enquiry["category"]}
        return self._prompt_loader.load_configured_prompt(promptConfigKey, prompt_variables)
