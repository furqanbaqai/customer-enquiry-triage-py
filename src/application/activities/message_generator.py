import asyncio
import json
from collections.abc import Callable
from typing import Any

from temporalio import activity

from src.utilities import OpenAIUtility, PromptLoader


class MessageGenerator:
    """Temporal activity for generating response messages."""

    def __init__(
        self,
        prompt_loader: PromptLoader | None = None,
        prompt_sender: Callable[[str], dict[str, object]] | None = None,
        response_prompt_configuration_key: str = "OFTL_AI_PROMPT_2",
    ) -> None:
        self._prompt_loader = prompt_loader or PromptLoader()
        self._func_OpenaiUtil_callJSON = prompt_sender or OpenAIUtility().callJson
        self._response_prompt_configuration_key = response_prompt_configuration_key

    @activity.defn(name="Generate Response Message from Incoming Enquiry using RAG pipeline")
    async def generate_response_message(
        self, message: dict[str, Any], emotions: str
    ) -> dict[str, Any]:
        """Generate a response message from the supplied JSON object."""

        activity.logger.info("Message response generation initiated")
        return await asyncio.to_thread(self._getAIResponseMessage, message, emotions)

    def _getAIResponseMessage(
        self, enquiry_message: dict[str, object], emotionType: str
    ) -> dict[str, object]:
        """Generate an emotion-aware response for the customer enquiry."""
        activity.logger.info(
            "[CEP] Loading Prompt from %s.", self._response_prompt_configuration_key
        )
        prompt_variables = {
            "INPUT_MESSAGE": enquiry_message["message"],
            "INPUT_EMOTION": emotionType,
            "PRODUCT_INFORMATION": enquiry_message["category"],
        }
        prompt = self._prompt_loader.load_configured_prompt(
            self._response_prompt_configuration_key, prompt_variables
        )
        activity.logger.debug("[CEP] Generated prompt for AI response: %s", prompt)
        activity.logger.info("[CEP] Customer enquiry submitted for AI response generation.")
        resp_aiResponseMessage = self._func_OpenaiUtil_callJSON(prompt)
        activity.logger.info("[CEP] AI response generation completed successfully.")
        activity.logger.debug("[CEP] AI generated response: %s", json.dumps(resp_aiResponseMessage))
        return resp_aiResponseMessage
