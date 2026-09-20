# -*- coding: utf-8 -*-

"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md\
Description: Defines the application entry point and composes the customer enquiry triage service.\
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py/blob/main/src/app.py\
"""

# ruff: noqa: E501, UP009 -- The banner is intentionally wide; the header requires UTF-8.

import asyncio
import os
import signal
import tomllib
from concurrent.futures import Executor, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

from src.application.CustomerEnquiryClient import CustomerEnquiryClient
from src.application.CustomerEnquiryWorker import CustomerEnquiryWorker
from src.config import ConfigLoader
from src.infrastructure import IBMMQClient, IBMMQSettings
from src.utilities import Logging, ResponseMessageUtility

_PROJECT_FILE = Path(__file__).resolve().parents[1] / "pyproject.toml"


def on_message(**kwargs: Any) -> None:
    """Handle a message delivered asynchronously from the request queue."""
    try:
        message = kwargs.get("msg")
        callback_context = kwargs.get("cbc")
        if callback_context is not None and callback_context.Reason != 0:
            Logging.error("IBM MQ callback reported reason code %s", callback_context.Reason)
            return

        message_length = callback_context.DataLength if callback_context is not None else None
        payload = message[:message_length] if message is not None else b""
        Logging.info("Received IBM MQ request message (%d bytes).", len(payload))
        CustomerEnquiryClient.sendToWorkflow(payload)
    except Exception as exception:
        Logging.error("[ERR-03] Failed to process IBM MQ request message: %s", exception)


def dispatch_message(
    executor: Executor,
    **kwargs: Any,
) -> None:
    """Copy an MQ delivery and submit it to the application worker.

    IBM MQ owns the callback buffers. Copying the payload before returning prevents the worker from
    reading memory that MQ has already reused for a subsequent delivery.
    """
    callback_context = kwargs.get("cbc")
    reason = callback_context.Reason if callback_context is not None else 0
    message_length = callback_context.DataLength if callback_context is not None else None
    message = kwargs.get("msg")
    payload = bytes(message[:message_length]) if message is not None else b""
    executor.submit(
        on_message,
        msg=payload,
        cbc=_CallbackContext(reason=reason, data_length=len(payload)),
    )


class _CallbackContext:
    """Worker-safe subset of the MQ callback context used by ``on_message``."""

    def __init__(self, reason: int, data_length: int) -> None:
        self.Reason = reason
        self.DataLength = data_length


def main(attMode: str = "") -> None:
    """Run the mode configured by the ``OFTL_RUN_MODE`` environment variable."""

    ConfigLoader.load_configurations()
    mode = attMode if attMode != "" else (ConfigLoader.get("OFTL_RUN_MODE") | "CLIENT")
    display_banner()
    display_project_information(startupMode=mode)

    if mode == "CLIENT":
        _run_mq_client()
    elif mode == "WORKER":
        result_client = IBMMQClient(IBMMQSettings.from_config())
        try:
            asyncio.run(CustomerEnquiryWorker.start(ResponseMessageUtility(result_client)))
        except KeyboardInterrupt:
            Logging.info("[CEP] Customer enquiry Temporal worker stopped by user.")
        finally:
            result_client.close()
    else:
        Logging.error("Unknown startup mode: %s", mode)
        return


def main_client() -> None:
    """Run the IBM MQ client mode."""
    main(attMode="CLIENT")


def main_worker() -> None:
    """Run the IBM MQ client mode."""
    main(attMode="WORKER")


def _run_mq_client() -> None:
    """Start the IBM MQ consumer and wait for shutdown."""

    client = IBMMQClient(IBMMQSettings.from_config())
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="enquiry-worker")
    stop_event = Event()

    def request_shutdown(_signum: int, _frame: Any) -> None:
        """Request a graceful shutdown from a console signal."""
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_shutdown)
    sigtstp = getattr(signal, "SIGTSTP", None)
    if os.name == "posix" and sigtstp is not None:
        signal.signal(sigtstp, request_shutdown)

    try:
        client.start_consumer(lambda **kwargs: dispatch_message(executor, **kwargs))
        Logging.info("[CEP] Customer enquiry triage client service is consuming IBM MQ requests.")
        Logging.info("[CEP] Waiting for the message ...")
        stop_event.wait()
    except (KeyboardInterrupt, EOFError):
        Logging.info("[CEP] Customer enquiry triage service is stopping.")
        exit(1)
    except Exception as exception:
        # Logging.error("[CEP] Customer enquiry triage service encountered an error: %s", exception)
        print(f"[CEP] Customer enquiry triage service encountered an error: {exception}")
        exit(99)
    finally:
        client.close()
        executor.shutdown(wait=True)


def display_banner() -> None:
    """Display the application banner."""
    banner = """
        ███████╗███╗   ██╗ ██████╗ ██╗   ██╗██╗██████╗ ██╗   ██╗     █████╗  ██████╗ ███████╗███╗   ██╗████████╗
        ██╔════╝████╗  ██║██╔═══██╗██║   ██║██║██╔══██╗╚██╗ ██╔╝    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
        █████╗  ██╔██╗ ██║██║   ██║██║   ██║██║██████╔╝ ╚████╔╝     ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
        ██╔══╝  ██║╚██╗██║██║▄▄ ██║██║   ██║██║██╔══██╗  ╚██╔╝      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
        ███████╗██║ ╚████║╚██████╔╝╚██████╔╝██║██║  ██║   ██║       ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
        ╚══════╝╚═╝  ╚═══╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═╝  ╚═╝   ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
                                                                                                        """
    print(banner)


def display_project_information(project_file: Path = _PROJECT_FILE, startupMode: str = "") -> None:
    """Display the version and description declared in ``pyproject.toml``."""
    with project_file.open("rb") as file:
        configuration = tomllib.load(file)

    project = configuration.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"[ERR-01] Missing [project] section in {project_file}")

    version = project.get("version")
    description = project.get("description")
    if not isinstance(version, str) or not isinstance(description, str):
        raise ValueError(f"[ERR-02] Missing project version or description in {project_file}")

    print(f"Version: {version}")
    print(f"Description: {description}")
    print(f"Startup Mode: {startupMode}")
