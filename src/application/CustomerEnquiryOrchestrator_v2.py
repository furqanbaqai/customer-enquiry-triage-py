import json
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from src.application.activities.message_classifier import MessageClassifier
    from src.application.activities.message_generator import MessageGenerator
    from src.application.activities.message_parser import RequestMessageParser
    from src.application.activities.push_response_message import PUSHResponseMessage


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
    async def run(self, message: str) -> dict[str, Any] | None:
        """Run the orchestrator workflow."""
        workflow.logger.info("Starting CustomerEnquiryOrchaestrator workflow")
        AI_RETRY_POLICY = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=10),
            maximum_attempts=5,
        )
        PUBLISH_RETRY_POLICY = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=10),
            maximum_attempts=5,
        )
        parsed_message: dict[str, Any] | None = None
        _classification: dict[str, Any] | None = None
        _ai_response_message: dict[str, Any] | None = None
        processing_error: Exception | None = None
        error_code, error_message = "0000", "Success"
        stage = "parsing"
        try:
            # Retain a decoded original even when the validation activity fails.
            try:
                original = json.loads(message)
                if isinstance(original, dict):
                    parsed_message = original
            except json.JSONDecodeError:
                pass

            validated_message = await workflow.execute_activity(
                RequestMessageParser().parse_request_message,
                message,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=AI_RETRY_POLICY,
            )
            if not isinstance(validated_message, dict):
                raise ApplicationError("Request validation failed", non_retryable=True)
            parsed_message = validated_message

            stage = "classification"
            _classification = await workflow.execute_activity_method(
                MessageClassifier.classify_message,
                parsed_message,
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=9),
                retry_policy=AI_RETRY_POLICY,
            )
            if not isinstance(_classification, dict):
                _classification = None
                raise ValueError("The AI assessment must be a JSON object")
            emotion_type = _classification["emotionalType"]
            if not isinstance(emotion_type, str):
                raise ValueError("[ERR-40] The AI assessment emotional type must be a string")

            stage = "generation"
            _ai_response_message = await workflow.execute_activity_method(
                MessageGenerator.generate_response_message,
                args=[parsed_message, emotion_type],
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=9),
                retry_policy=AI_RETRY_POLICY,
            )
            if not isinstance(_ai_response_message, dict):
                _ai_response_message = None
                raise ValueError("The AI response must be a JSON object")
        except ActivityError as error:
            if is_cancelled_exception(error):
                raise
            processing_error = error
            error_code, error_message = {
                "parsing": ("8100", "Request validation failed"),
                "classification": ("8200", "Message classification failed"),
                "generation": ("8300", "Response generation failed"),
            }[stage]
            workflow.logger.error(
                "Enquiry activity failed (stage=%s, retry_state=%s)", stage, error.retry_state
            )
        except Exception as error:
            if is_cancelled_exception(error):
                raise
            processing_error = error
            error_code, error_message = "9999", "Unable to process the enquiry"
            workflow.logger.error(
                "Enquiry processing failed (stage=%s, type=%s)", stage, type(error).__name__
            )

        # Publishing has its own retry budget. Its failure must not recursively publish again.
        response: dict[str, Any] = await workflow.execute_activity_method(
            PUSHResponseMessage.push_response_message,
            args=[
                {
                    "parsed_message": parsed_message,
                    "_classification": _classification,
                    "_ai_response_message": _ai_response_message,
                },
                error_code,
                error_message,
            ],
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(minutes=3),
            retry_policy=PUBLISH_RETRY_POLICY,
        )
        if processing_error is not None:
            raise ApplicationError(
                error_message,
                error_code,
                type="CustomerEnquiryProcessingError",
                non_retryable=True,
            ) from processing_error
        workflow.logger.info("CustomerEnquiryOrchaestrator workflow completed successfully")
        return response
