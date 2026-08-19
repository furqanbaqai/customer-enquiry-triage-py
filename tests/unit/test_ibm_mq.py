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


def test_client_registers_and_stops_async_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_manager = MagicMock()
    queue = MagicMock()
    mq = ibm_mq_module.__dict__["ibmmq"]
    monkeypatch.setattr(mq, "connect", MagicMock(return_value=queue_manager))
    monkeypatch.setattr(mq, "Queue", MagicMock(return_value=queue))
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
    queue.cb.assert_any_call(
        operation=mq.CMQC.MQOP_DEREGISTER,
    )
    queue.close.assert_called_once_with()
    queue_manager.disconnect.assert_called_once_with()
