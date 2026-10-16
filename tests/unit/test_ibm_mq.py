import json
from unittest.mock import MagicMock

import pytest

from src.config import ConfigLoader
from src.infrastructure import IBMMQClient, IBMMQConfigurationError, IBMMQSettings
from src.infrastructure import ibm_mq as ibm_mq_module


def test_settings_load_queue_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    ConfigLoader.configurations = {
        "OFTL_IMQ_QMGR": "QM1",
        "OFTL_IMQ_CHANNEL": "CHANNEL",
        "OFTL_IMQ_LISTENER": "1414",
        "OFTL_IMQ_USERNAME": "user",
        "OFTL_IMQ_PASS": "password",
        "OFTL_IMQ_HOST": "mq.example.com",
    }

    settings = IBMMQSettings.from_config()

    assert settings.request_queue == "AI.CUST.ENQ.TRIAGE.REQUEST.Q"
    assert settings.result_queue == "AI.CUST.ENQ.TRIAGE.RESULT.Q"
    assert settings.backout_queue == "AI.CUST.ENQ.TRIAGE.BACKOUT.Q"
    monkeypatch.undo()
    ConfigLoader.configurations = {}


def test_settings_reject_missing_required_configuration() -> None:
    ConfigLoader.configurations = {"OFTL_IMQ_QMGR": "QM1"}

    with pytest.raises(IBMMQConfigurationError, match="OFTL_IMQ_CHANNEL"):
        IBMMQSettings.from_config()

    ConfigLoader.configurations = {}


def test_client_starts_and_stops_polling_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_manager = MagicMock()
    queue = MagicMock()
    consumer_thread = MagicMock()
    thread_factory = MagicMock(return_value=consumer_thread)
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=queue_manager))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=queue))
    monkeypatch.setattr(ibm_mq_module, "Thread", thread_factory)
    settings = IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host")
    callback = MagicMock()
    client = IBMMQClient(settings)

    client.start_consumer(callback)
    client.close()

    mq.connect.assert_called_once_with(
        "QM1",
        "CHANNEL",
        "host(1414)",
        user="user",
        password="password",
    )
    consumer_thread.start.assert_called_once_with()
    consumer_thread.join.assert_called_once_with(timeout=2)
    queue.close.assert_called_once_with()
    queue_manager.disconnect.assert_called_once_with()


def test_polling_consumer_delivers_consecutive_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_manager = MagicMock()
    queue = MagicMock()
    queue.get.side_effect = [b"first", b"second"]
    consumer_thread = MagicMock()
    thread_factory = MagicMock(return_value=consumer_thread)
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=queue_manager))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=queue))
    monkeypatch.setattr(ibm_mq_module, "Thread", thread_factory)
    client = IBMMQClient(IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host"))
    callback = MagicMock()
    callback.side_effect = lambda **_kwargs: (
        client._consumer_stop.set() if callback.call_count == 2 else None
    )

    client.start_consumer(callback)
    consume = thread_factory.call_args.kwargs["target"]
    consume(*thread_factory.call_args.kwargs["args"])

    assert [call.kwargs["msg"] for call in callback.call_args_list] == [b"first", b"second"]
    assert [call.kwargs["cbc"].DataLength for call in callback.call_args_list] == [5, 6]


def test_client_puts_utf8_json_on_configured_result_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_manager = MagicMock()
    result_queue = MagicMock()
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=queue_manager))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=result_queue))
    settings = IBMMQSettings(
        "QM1",
        "CHANNEL",
        1414,
        "user",
        "password",
        "host",
        result_queue="CUSTOM.RESULT.Q",
    )
    client = IBMMQClient(settings)
    message: dict[str, object] = {"aiGeneratedResponse": {"detailMessage": "مرحباً"}}

    client.put_result_message(message)
    client.close()

    descriptor = mq.Queue.call_args.args[1]
    assert descriptor.ObjectName == "CUSTOM.RESULT.Q"
    payload = result_queue.put.call_args.args[0]
    assert json.loads(payload.decode("utf-8")) == message
    result_queue.close.assert_called_once_with()
    queue_manager.disconnect.assert_called_once_with()


def test_client_uses_separate_connections_for_consumer_and_result_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer_manager = MagicMock()
    result_manager = MagicMock()
    request_queue = MagicMock()
    result_queue = MagicMock()
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(side_effect=[consumer_manager, result_manager]))
    monkeypatch.setattr(mq, "Queue", MagicMock(side_effect=[request_queue, result_queue]))
    monkeypatch.setattr(ibm_mq_module, "Thread", MagicMock(return_value=MagicMock()))
    client = IBMMQClient(IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host"))

    client.start_consumer(MagicMock())
    client.put_result_message({"responseCode": "0000"})
    client.close()

    assert mq.connect.call_count == 2
    assert mq.Queue.call_args_list[0].args[0] is consumer_manager
    assert mq.Queue.call_args_list[1].args[0] is result_manager
    consumer_manager.disconnect.assert_called_once_with()
    result_manager.disconnect.assert_called_once_with()


def test_client_translates_result_queue_put_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_manager = MagicMock()
    result_queue = MagicMock()
    result_queue.put.side_effect = OSError("queue unavailable")
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=queue_manager))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=result_queue))
    client = IBMMQClient(IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host"))

    with pytest.raises(RuntimeError, match=r"\[ERR-38\]"):
        client.put_result_message({})


@pytest.mark.parametrize(
    "operation", ["connect", "open", "get", "result_connect", "result_open", "put"]
)
@pytest.mark.parametrize("reason", [2009, 2059, 2161])
def test_mq_failure_notifies_process_owner(
    monkeypatch: pytest.MonkeyPatch, operation: str, reason: int
) -> None:
    mq = ibm_mq_module.__dict__["ibmmq"]
    failure = mq.MQMIError(2, reason)
    queue = MagicMock()
    connect = MagicMock(return_value=MagicMock())
    open_queue = MagicMock(return_value=queue)
    monkeypatch.setattr(mq, "connect", connect)
    monkeypatch.setattr(mq, "Queue", open_queue)
    monkeypatch.setattr(ibm_mq_module, "Thread", MagicMock())
    on_fatal_error = MagicMock()
    client = IBMMQClient(
        IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host"),
        on_fatal_error=on_fatal_error,
    )

    if operation in {"connect", "result_connect"}:
        connect.side_effect = failure
    elif operation in {"open", "result_open"}:
        open_queue.side_effect = failure
    elif operation == "put":
        queue.put.side_effect = failure
    else:
        queue.get.side_effect = failure

    callback = MagicMock()
    if operation == "get":
        client.start_consumer(callback)
        client._consume_messages(callback)
        callback.assert_not_called()
        queue.get.assert_called_once()
    elif operation.startswith("result_") or operation == "put":
        with pytest.raises(RuntimeError, match=r"\[ERR-38\]") as error:
            client.put_result_message({})
        assert error.value.__cause__ is failure
    else:
        with pytest.raises(mq.MQMIError) as error:
            client.start_consumer(callback)
        assert error.value is failure

    on_fatal_error.assert_called_once_with(failure)
    assert client._consumer_stop.is_set()


def test_empty_queue_continues_polling_without_fatal_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mq = ibm_mq_module.__dict__["ibmmq"]
    queue = MagicMock()
    queue.get.side_effect = [mq.MQMIError(2, mq.CMQC.MQRC_NO_MSG_AVAILABLE), b"next"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=queue))
    monkeypatch.setattr(ibm_mq_module, "Thread", MagicMock())
    fatal = MagicMock()
    client = IBMMQClient(IBMMQSettings("QM1", "CHANNEL", 1414, "user", "password", "host"), fatal)
    callback = MagicMock(side_effect=lambda **_kwargs: client._consumer_stop.set())
    client.start_consumer(callback)
    client._consume_messages(callback)

    assert queue.get.call_count == 2
    callback.assert_called_once()
    assert callback.call_args.kwargs["msg"] == b"next"
    fatal.assert_not_called()
