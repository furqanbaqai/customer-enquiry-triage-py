from typing import Any

from temporalio import activity


class MessageGenerator:
    """Temporal activity for generating response messages."""

    @activity.defn(name="Generate Response Message from Incoming Enquiry using RAG pipeline")
    async def generate_response_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Generate a response message from the supplied JSON object."""
        return {"message": message}
