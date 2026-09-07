from temporalio import workflow


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
    async def run(self, message: str) -> str:
        """Run the orchestrator workflow."""
        return f"Processed message: {message}"
