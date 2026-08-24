# -*- coding: utf-8 -*-

"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md\
Description: Defines IBM MQ settings, validation, connections, and asynchronous consumption.\
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py/blob/main/src/infrastructure/ibm_mq.py\
"""

# ruff: noqa: UP009 -- The project copyright header requires an encoding declaration.

import json
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any

import ibmmq  # type: ignore[import-untyped]  # The vendor package does not publish type data.

from src.config import ConfigLoader
from src.utilities import Logging

MessageCallback = Callable[..., None]


class IBMMQConfigurationError(ValueError):
    """Raised when the IBM MQ configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class IBMMQSettings:
    """Connection and queue names required by the IBM MQ adapter."""

    queue_manager: str
    channel: str
    listener: int
    username: str
    password: str
    host: str
    request_queue: str = "AI.CUST.ENQ.TRIAGE.REQUEST.Q"
    result_queue: str = "AI.CUST.ENQ.TRIAGE.RESULT.Q"
    backout_queue: str = "AI.CUST.ENQ.TRIAGE.BACKOUT.Q"

    @classmethod
    def from_config(cls) -> "IBMMQSettings":
        """Build and validate settings from the loaded application configuration."""
        required_keys = (
            "OFTL_IMQ_QMGR",
            "OFTL_IMQ_CHANNEL",
            "OFTL_IMQ_LISTENER",
            "OFTL_IMQ_USERNAME",
            "OFTL_IMQ_PASS",
            "OFTL_IMQ_HOST",
        )
        missing = [key for key in required_keys if not ConfigLoader.get(key)]
        if missing:
            raise IBMMQConfigurationError(
                f"[ERR-10] Missing required IBM MQ configuration: {', '.join(missing)}"
            )

        listener_value = str(ConfigLoader.get("OFTL_IMQ_LISTENER"))
        try:
            listener = int(listener_value)
        except ValueError as exc:
            raise IBMMQConfigurationError("[ERR-11] OFTL_IMQ_LISTENER must be an integer") from exc

        if not 1 <= listener <= 65535:
            raise IBMMQConfigurationError("[ERR-12] OFTL_IMQ_LISTENER must be between 1 and 65535")

        return cls(
            queue_manager=str(ConfigLoader.get("OFTL_IMQ_QMGR")),
            channel=str(ConfigLoader.get("OFTL_IMQ_CHANNEL")),
            listener=listener,
            username=str(ConfigLoader.get("OFTL_IMQ_USERNAME")),
            password=str(ConfigLoader.get("OFTL_IMQ_PASS")),
            host=str(ConfigLoader.get("OFTL_IMQ_HOST")),
            request_queue=str(
                ConfigLoader.get("OFTL_IMQ_REQUEST_QUEUE", "AI.CUST.ENQ.TRIAGE.REQUEST.Q")
            ),
            result_queue=str(
                ConfigLoader.get("OFTL_IMQ_RESULT_QUEUE", "AI.CUST.ENQ.TRIAGE.RESULT.Q")
            ),
            backout_queue=str(
                ConfigLoader.get("OFTL_IMQ_BACKOUT_QUEUE", "AI.CUST.ENQ.TRIAGE.BACKOUT.Q")
            ),
        )


class IBMMQClient:
    """Manage an IBM MQ client connection and asynchronous request consumer."""

    def __init__(self, settings: IBMMQSettings) -> None:
        self._settings = settings
        self._queue_manager: Any | None = None
        self._result_queue_manager: Any | None = None
        self._request_queue: Any | None = None
        self._result_queue: Any | None = None
        self._consumer_stop = Event()
        self._consumer_thread: Thread | None = None

    def connect(self) -> None:
        """Connect to the configured queue manager using client credentials."""
        if self._queue_manager is not None:
            return

        connection_name = f"{self._settings.host}({self._settings.listener})"
        self._queue_manager = ibmmq.connect(
            self._settings.queue_manager,
            self._settings.channel,
            connection_name,
            user=self._settings.username,
            password=self._settings.password,
        )

    def start_consumer(self, callback: MessageCallback) -> None:
        """Open the request queue and start bounded MQGET polling on a worker thread."""
        Logging.info(
            "[IBM-MQ]]Starting IBM MQ consumer for queue: %s", self._settings.request_queue
        )
        Logging.debug("[IBM-MQ] IBM MQ settings: %s", self._settings)
        self.connect()
        queue_manager = self._queue_manager
        if queue_manager is None:
            raise RuntimeError("[ERR-13] IBM MQ connection was not established")
        if self._request_queue is not None:
            raise RuntimeError("[ERR-14] IBM MQ consumer is already running")

        object_descriptor = ibmmq.OD()
        object_descriptor.ObjectName = self._settings.request_queue
        self._request_queue = ibmmq.Queue(
            queue_manager,
            object_descriptor,
            ibmmq.CMQC.MQOO_INPUT_AS_Q_DEF | ibmmq.CMQC.MQOO_FAIL_IF_QUIESCING,
        )

        self._consumer_stop.clear()
        self._consumer_thread = Thread(
            target=self._consume_messages,
            args=(callback,),
            name="ibm-mq-consumer",
            daemon=True,
        )
        self._consumer_thread.start()
        Logging.info("[IBM-MQ] IBM MQ consumer started for queue: %s", self._settings.request_queue)

    def _consume_messages(self, callback: MessageCallback) -> None:
        """Poll the request queue and deliver each message using the callback contract."""
        request_queue = self._request_queue
        queue_manager = self._queue_manager
        if request_queue is None or queue_manager is None:
            Logging.error("[ERR-41] IBM MQ request consumer is not initialized")
            return

        get_options = ibmmq.GMO()
        get_options.Options = (
            ibmmq.CMQC.MQGMO_NO_SYNCPOINT
            | ibmmq.CMQC.MQGMO_WAIT
            | ibmmq.CMQC.MQGMO_FAIL_IF_QUIESCING
        )
        get_options.WaitInterval = 1000

        while not self._consumer_stop.is_set():
            message_descriptor = ibmmq.MD()
            try:
                message = request_queue.get(None, message_descriptor, get_options)
            except ibmmq.MQMIError as error:
                if error.reason == ibmmq.CMQC.MQRC_NO_MSG_AVAILABLE:
                    continue
                Logging.error("[ERR-42] IBM MQ request polling failed: %s", error)
                return
            callback(
                queue_manager=queue_manager,
                queue=request_queue,
                md=message_descriptor,
                gmo=get_options,
                msg=message,
                cbc=_DeliveryContext(Reason=0, DataLength=len(message)),
            )

    def put_result_message(self, message: dict[str, object]) -> None:
        """Serialize and put a response message on the configured result queue."""
        try:
            if self._result_queue_manager is None:
                connection_name = f"{self._settings.host}({self._settings.listener})"
                self._result_queue_manager = ibmmq.connect(
                    self._settings.queue_manager,
                    self._settings.channel,
                    connection_name,
                    user=self._settings.username,
                    password=self._settings.password,
                )
            result_queue_manager = self._result_queue_manager
            if result_queue_manager is None:
                raise RuntimeError("[ERR-40] IBM MQ result connection was not established")

            if self._result_queue is None:
                object_descriptor = ibmmq.OD()
                object_descriptor.ObjectName = self._settings.result_queue
                self._result_queue = ibmmq.Queue(
                    result_queue_manager,
                    object_descriptor,
                    ibmmq.CMQC.MQOO_OUTPUT | ibmmq.CMQC.MQOO_FAIL_IF_QUIESCING,
                )

            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._result_queue.put(payload)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError("[ERR-38] Unable to put the response message on IBM MQ") from error
        Logging.info("[IBM-MQ] Response message put on queue: %s", self._settings.result_queue)

    def close(self) -> None:
        """Stop async delivery and release the queue and queue-manager handles."""
        self._consumer_stop.set()
        if self._consumer_thread is not None:
            self._consumer_thread.join(timeout=2)
            self._consumer_thread = None

        if self._request_queue is not None and self._queue_manager is not None:
            self._request_queue.close()
            self._request_queue = None

        if self._result_queue is not None:
            self._result_queue.close()
            self._result_queue = None

        if self._result_queue_manager is not None:
            self._result_queue_manager.disconnect()
            self._result_queue_manager = None

        if self._queue_manager is not None:
            self._queue_manager.disconnect()
            self._queue_manager = None

    def __enter__(self) -> "IBMMQClient":
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class _DeliveryContext:
    """Subset of MQ callback context consumed by the application boundary."""

    Reason: int
    DataLength: int
