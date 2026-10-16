import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from temporalio import activity

from src.config import ConfigLoader
from src.utilities import OpenAIUtility, PromptLoader


class MessageGenerator:
    """Temporal activity for generating response messages."""

    def __init__(
        self,
        prompt_loader: PromptLoader | None = None,
        prompt_sender: Callable[[str], dict[str, object]] | None = None,
        response_prompt_configuration_key: str = "OFTL_AI_PROMPT_2",
        product_catalogue_key: str = "OFTL_AI_PRODUCTCAT",
    ) -> None:
        self._prompt_loader = prompt_loader or PromptLoader()
        self._func_OpenaiUtil_callJSON = prompt_sender or OpenAIUtility().callJson
        self._response_prompt_configuration_key = response_prompt_configuration_key
        self._product_catalogue_key = product_catalogue_key

    @activity.defn(name="Generate Response Message from Incoming Enquiry using RAG pipeline")
    async def generate_response_message(
        self, message: str, product_code: str, emotions: str
    ) -> dict[str, Any]:
        """Generate a response message from the supplied JSON object."""

        activity.logger.info("Message response generation initiated")
        return await asyncio.to_thread(self._getAIResponseMessage, message, product_code, emotions)

    def _getAIResponseMessage(
        self, enquiry_message: str, product_code: str, emotionType: str
    ) -> dict[str, object]:
        """Generate an emotion-aware response for the customer enquiry."""
        activity.logger.info(
            "[CEP] Loading Prompt from %s.", self._response_prompt_configuration_key
        )

        product_catalogue = ConfigLoader.get(self._product_catalogue_key)
        product_json_folder = (
            Path(product_catalogue)
            if product_catalogue
            else Path(__file__).resolve().parents[3] / "prompts" / "product_json"
        )
        product_json_path = product_json_folder / f"{product_code}.json"
        activity.logger.info("[CEP] Loading product information from %s.", product_json_path)
        with product_json_path.open(encoding="utf-8") as product_file:
            product_information = json.dumps(json.load(product_file))
            activity.logger.debug("[CEP] Loaded product information: %s", product_information)

        prompt_variables = {
            "INPUT_MESSAGE": enquiry_message,
            "INPUT_EMOTION": emotionType,
            "PRODUCT_INFORMATION": product_information,
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
