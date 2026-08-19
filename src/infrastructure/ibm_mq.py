# -*- coding: utf-8 -*-

"""\
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.\
Licenses: LICENSE.md\
Description: Defines IBM MQ settings, validation, connections, and asynchronous consumption.\
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py/blob/main/src/infrastructure/ibm_mq.py\
"""

# ruff: noqa: UP009 -- The project copyright header requires an encoding declaration.

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import ibmmq  # type: ignore[import-untyped]  # The vendor package does not publish type data.

from src.config import ConfigLoader

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
                f"Missing required IBM MQ configuration: {', '.join(missing)}"
            )

        listener_value = str(ConfigLoader.get("OFTL_IMQ_LISTENER"))
        try:
            listener = int(listener_value)
        except ValueError as exc:
            raise IBMMQConfigurationError("OFTL_IMQ_LISTENER must be an integer") from exc

        if not 1 <= listener <= 65535:
            raise IBMMQConfigurationError("OFTL_IMQ_LISTENER must be between 1 and 65535")

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
        self._request_queue: Any | None = None
        self._control_options: Any | None = None

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
        """Open the request queue, register ``callback``, and start MQ async delivery."""
        self.connect()
        queue_manager = self._queue_manager
        if queue_manager is None:
            raise RuntimeError("IBM MQ connection was not established")
        if self._request_queue is not None:
            raise RuntimeError("IBM MQ consumer is already running")

        object_descriptor = ibmmq.OD()
        object_descriptor.ObjectName = self._settings.request_queue
        self._request_queue = ibmmq.Queue(
            queue_manager,
            object_descriptor,
            ibmmq.CMQC.MQOO_INPUT_AS_Q_DEF | ibmmq.CMQC.MQOO_FAIL_IF_QUIESCING,
        )

        get_options = ibmmq.GMO()
        get_options.Options = (
            ibmmq.CMQC.MQGMO_NO_SYNCPOINT
            | ibmmq.CMQC.MQGMO_WAIT
            | ibmmq.CMQC.MQGMO_FAIL_IF_QUIESCING
        )
        get_options.WaitInterval = ibmmq.CMQC.MQWI_UNLIMITED

        callback_descriptor = ibmmq.CBD()
        callback_descriptor.CallbackFunction = callback
        callback_descriptor.CallbackType = ibmmq.CMQC.MQCBT_MESSAGE_CONSUMER
        self._request_queue.cb(
            operation=ibmmq.CMQC.MQOP_REGISTER,
            cbd=callback_descriptor,
            md=ibmmq.MD(),
            gmo=get_options,
        )

        self._control_options = ibmmq.CTLO()
        queue_manager.ctl(ibmmq.CMQC.MQOP_START, self._control_options)

    def close(self) -> None:
        """Stop async delivery and release the queue and queue-manager handles."""
        if self._queue_manager is None:
            return

        if self._request_queue is not None:
            if self._control_options is not None:
                self._queue_manager.ctl(ibmmq.CMQC.MQOP_STOP, self._control_options)
            self._request_queue.cb(operation=ibmmq.CMQC.MQOP_DEREGISTER)
            self._request_queue.close()
            self._request_queue = None
            self._control_options = None

        self._queue_manager.disconnect()
        self._queue_manager = None

    def __enter__(self) -> "IBMMQClient":
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
