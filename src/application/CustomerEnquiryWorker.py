"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Hosts the customer enquiry Temporal workflow and activities.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from src.application.activities.message_classifier import MessageClassifier
from src.application.activities.message_generator import MessageGenerator
from src.application.activities.message_parser import RequestMessageParser
from src.application.activities.push_response_message import PUSHResponseMessage
from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator
from src.config import ConfigLoader
from src.utilities import Logging, ResponseMessageUtility


class CustomerEnquiryWorker:
    """Run the Temporal worker for the lifetime of WORKER mode."""

    @staticmethod
    async def start(response_message_utility: ResponseMessageUtility) -> None:
        """Connect once and poll until cancelled or a worker failure occurs."""
        endpoint = ConfigLoader.get("OFTL_AI_TEMPORALURL", "localhost:7233")
        if not isinstance(endpoint, str) or not endpoint.strip():
            Logging.error("OFTL_AI_TEMPORALURL must be a non-empty string.")
            raise ValueError("OFTL_AI_TEMPORALURL must be a non-empty string.")

        try:
            async with asyncio.timeout(30):
                client = await Client.connect(endpoint.strip())
            classifier = MessageClassifier()
            generator = MessageGenerator()
            parser = RequestMessageParser()
            publisher = PUSHResponseMessage(response_message_utility)
            worker = Worker(
                client,
                task_queue="CUSTOMER.ENQUIRY.REQUEST",
                workflows=[CustomerEnquiryOrchaestrator],
                activities=[
                    parser.parse_request_message,
                    classifier.classify_message,
                    generator.generate_response_message,
                    publisher.push_response_message,
                ],
                graceful_shutdown_timeout=timedelta(minutes=10),
                max_concurrent_activities=2,
            )
            Logging.info("Temporal worker started on task queue CUSTOMER.ENQUIRY.REQUEST.")
            await worker.run()
        except asyncio.CancelledError:
            Logging.info("Temporal customer enquiry worker stopped.")
            raise
        except Exception as exception:
            Logging.error("Temporal customer enquiry worker failed (%s).", type(exception).__name__)
            raise RuntimeError("Temporal customer enquiry worker failed.") from exception
