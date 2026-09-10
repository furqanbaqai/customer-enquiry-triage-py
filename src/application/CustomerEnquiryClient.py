"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Validates customer enquiries and forwards them to Temporal workflows.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from src.application.CustomerEnquiryOrchestrator_v2 import CustomerEnquiryOrchaestrator
from src.config import ConfigLoader
from src.utilities import Logging

_SCHEMA_FILE_NAME = "enquiry-request-v1.0.json"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / _SCHEMA_FILE_NAME


class CustomerEnquiryClient:
    """Submit validated enquiries from synchronous application workers."""

    @staticmethod
    def sendToWorkflow(payload: bytes) -> None:
        """Validate UTF-8 JSON and wait for workflow completion; raise on failure.

        Call from a synchronous thread without a running asyncio event loop.
        """
        try:
            enquiry = json.loads(payload.decode("utf-8"))
            Logging.info("Customer enquiry is valid UTF-8 JSON.")
        except (UnicodeDecodeError, json.JSONDecodeError) as exception:
            Logging.error("Customer enquiry is not valid UTF-8 JSON.")
            raise ValueError("Customer enquiry is not valid UTF-8 JSON.") from exception

        try:
            with _SCHEMA_PATH.open(encoding="utf-8") as schema_file:
                schema = json.load(schema_file)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(
                schema, format_checker=Draft202012Validator.FORMAT_CHECKER
            )
        except Exception as exception:
            Logging.error(
                "Unable to load the customer enquiry schema (%s).", type(exception).__name__
            )
            raise RuntimeError("Unable to load the customer enquiry schema.") from exception

        try:
            validator.validate(enquiry)
            Logging.info(
                "Customer enquiry passed schema validation using schema %s.", _SCHEMA_FILE_NAME
            )
        except ValidationError as exception:
            Logging.error("Customer enquiry failed schema validation.")
            raise ValueError("Customer enquiry failed schema validation.") from exception

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(CustomerEnquiryClient._async_send_message(enquiry))
        else:
            Logging.error(
                "sendToWorkflow requires a synchronous thread without an active event loop."
            )
            raise RuntimeError("sendToWorkflow cannot run inside an active asyncio event loop.")

    @staticmethod
    async def _async_send_message(payload: dict[str, object]) -> None:
        """Send an already validated enquiry as JSON to the v2 workflow."""
        endpoint = ConfigLoader.get("OFTL_AI_TEMPORALURL", "localhost:7233")
        if not isinstance(endpoint, str) or not endpoint.strip():
            Logging.error("OFTL_AI_TEMPORALURL must be a non-empty string.")
            raise ValueError("OFTL_AI_TEMPORALURL must be a non-empty string.")

        meta = payload.get("meta")
        reference = meta.get("refNumber") if isinstance(meta, dict) else None
        if not isinstance(reference, str) or not reference:
            raise ValueError("A validated enquiry with meta.refNumber is required.")
        channel = meta.get("channel") if isinstance(meta, dict) else None
        if not isinstance(channel, str) or not channel:
            raise ValueError("A validated enquiry with meta.channle is required.")
        workflow_id = f"CE-{channel.upper()}-{reference}"

        try:
            async with asyncio.timeout(30):
                client = await Client.connect(endpoint.strip())

            result = await client.start_workflow(
                CustomerEnquiryOrchaestrator.run,
                json.dumps(payload, ensure_ascii=False),
                id=workflow_id,
                task_queue="CUSTOMER.ENQUIRY.REQUEST",
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=timedelta(minutes=25),
                task_timeout=timedelta(seconds=10),
                rpc_timeout=timedelta(seconds=60),
            )
            Logging.info("Temporal message publish for workflow with workflow ID %s", workflow_id)
            Logging.debug("Temporal workflow result: %s", result)
        except Exception as exception:
            Logging.error("Temporal enquiry execution failed (%s).", type(exception).__name__)
            raise RuntimeError("Temporal enquiry execution failed.") from exception
