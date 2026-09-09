from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from src.application.activities.message_classifier import MessageClassifier
from src.application.activities.message_parser import RequestMessageParser


@workflow.defn(name="Workflow for orchestrating the processing of a customer enquiry message")
class CustomerEnquiryOrchaestrator:
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

    @workflow.run
    async def run(self, message: str) -> bool:
        """Run the orchestrator workflow."""
        workflow.logger.info("Starting CustomerEnquiryOrchaestrator workflow")
        workflow.logger.debug("Received message for processing: %s", message)
        # Definition of retrial policy
        AI_RETRY_POLICY = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=10),
            maximum_attempts=5,
        )
        # Parse the message and validate it
        parsed_message: dict | None = await workflow.execute_activity(
            RequestMessageParser().parse_request_message,
            message,
            start_to_close_timeout=timedelta(seconds=30),
        )
        if not parsed_message:
            workflow.logger.error("Failed to parse and validate the incoming message: %s", message)
            return False
        # END;

        # Call message classification activity
        _classification = await workflow.execute_activity(
            MessageClassifier().classify_message,
            parsed_message,
            start_to_close_timeout=timedelta(seconds=300),
            retry_policy=AI_RETRY_POLICY,
        )
        # ENd;

        workflow.logger.info("CustomerEnquiryOrchaestrator workflow completed successfully")
        return True
