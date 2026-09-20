import asyncio
import json
from collections.abc import Callable
from typing import Any

from temporalio import activity

from src.utilities import OpenAIUtility, PromptLoader


class MessageClassifier:
    def __init__(
        self,
        prompt_loader: PromptLoader | None = None,
        prompt_sender: Callable[[str], dict[str, object]] | None = None,
        prompt_configuration_key: str = "OFTL_AI_PROMPT_1",
    ) -> None:
        self._prompt_loader = prompt_loader or PromptLoader()
        self._func_OpenaiUtil_callJSON = prompt_sender or OpenAIUtility().callJson
        self._prompt_configuration_key = prompt_configuration_key

    @activity.defn(name="Classify Incoming Enquiry Message using LLM")
    async def classify_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Classify a message and return a JSON-compatible response."""
        activity.logger.info("Message classification initiated")

        return await asyncio.to_thread(self._getAIAssesment, message)

    def _getAIAssesment(self, enquiry_message: dict[str, object]) -> dict[str, object]:
        """Generate an AI assessment for the customer enquiry."""
        activity.logger.info("[CEP] Loading Prompt from %s.", self._prompt_configuration_key)
        prompt = self._generate_prompt(enquiry_message, self._prompt_configuration_key)
        activity.logger.debug("[CEP] Generated prompt for AI response: %s", prompt)
        activity.logger.info("[CEP] Customer enquiry submitted for AI classification.")
        resp_aiAssesment = self._func_OpenaiUtil_callJSON(prompt)
        activity.logger.info("[CEP] AI classification completed successfully.")
        activity.logger.debug("[CEP] AI classification result: %s", json.dumps(resp_aiAssesment))
        return resp_aiAssesment

    def _generate_prompt(self, enquiry: dict[str, object], prompt_configuration_key: str) -> str:
        """Render the classification prompt using the enquiry message and category."""
        return self._prompt_loader.load_configured_prompt(
            prompt_configuration_key,
            {"MESSAGE": enquiry["message"], "CATEGORY": enquiry["category"]},
        )
