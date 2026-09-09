from typing import Any

from temporalio import activity


class MessageClassifier:
    @activity.defn(name="Classify Incoming Enquiry Message using LLM")
    async def classify_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Classify a message and return a JSON-compatible response."""
        activity.logger.info("Message classification initiated")

        return {"message": message}
