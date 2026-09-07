import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import app
from src.config import ConfigLoader
from src.infrastructure import IBMMQSettings


def test_display_project_information(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text(
        '[project]\nversion = "1.2.3"\ndescription = "Example service"\n',
        encoding="utf-8",
    )

    app.display_project_information(project_file)

    assert capsys.readouterr().out == "Version: 1.2.3\nDescription: Example service\n"


def test_main_starts_consumer(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="OFTL")
    client = MagicMock()
    executor = MagicMock()
    wait_event = MagicMock()
    monkeypatch.setattr(ConfigLoader, "load_configurations", MagicMock())
    monkeypatch.setattr(IBMMQSettings, "from_config", MagicMock())
    monkeypatch.setattr(app, "IBMMQClient", MagicMock(return_value=client))
    monkeypatch.setattr(app, "Event", MagicMock(return_value=wait_event))
    monkeypatch.setattr(app, "ThreadPoolExecutor", MagicMock(return_value=executor))

    app.main("CLIENT")

    client.start_consumer.assert_called_once()
    callback = client.start_consumer.call_args.args[0]
    callback(msg=b"customer request", cbc=MagicMock(Reason=0, DataLength=8))
    executor.submit.assert_called_once()
    submitted = executor.submit.call_args
    submitted.args[0](*submitted.args[1:], **submitted.kwargs)
    assert "[CEP] Customer enquiry triage service is consuming IBM MQ requests." in caplog.messages
    assert "Received IBM MQ request message (8 bytes)." in caplog.messages
    client.close.assert_called_once_with()
    executor.shutdown.assert_called_once_with(wait=True)


def test_dispatch_message_copies_mq_buffer_before_submitting() -> None:
    executor = MagicMock()
    buffer = bytearray(b"first messagetrailing bytes")

    app.dispatch_message(
        executor,
        msg=buffer,
        cbc=MagicMock(Reason=0, DataLength=13),
    )
    buffer[:] = b"buffer reused by IBM MQ...."

    submitted = executor.submit.call_args
    assert submitted.args == (app.on_message,)
    assert submitted.kwargs["msg"] == b"first message"
    assert submitted.kwargs["cbc"].DataLength == 13


@pytest.mark.parametrize("from_cli", [False, True])
def test_worker_mode_does_not_start_client(monkeypatch: pytest.MonkeyPatch, from_cli: bool) -> None:
    client_factory = MagicMock()
    configuration_loader = MagicMock()
    monkeypatch.setattr(app, "IBMMQClient", client_factory)
    monkeypatch.setattr(ConfigLoader, "load_configurations", configuration_loader)
    monkeypatch.setattr(sys, "argv", ["customer-enquiry-triage", "WORKER"])

    app.main(None if from_cli else "WORKER")

    client_factory.assert_not_called()
    configuration_loader.assert_not_called()


def test_cli_client_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    run_client = MagicMock()
    monkeypatch.setattr(app, "_run_client", run_client)
    monkeypatch.setattr(sys, "argv", ["customer-enquiry-triage", "CLIENT"])

    app.main()

    run_client.assert_called_once_with()


@pytest.mark.parametrize("arguments", [[], ["UNKNOWN"]])
def test_cli_requires_valid_mode(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> None:
    client_factory = MagicMock()
    monkeypatch.setattr(app, "IBMMQClient", client_factory)
    monkeypatch.setattr(sys, "argv", ["customer-enquiry-triage", *arguments])

    with pytest.raises(SystemExit) as error:
        app.main()

    assert error.value.code == 2
    client_factory.assert_not_called()


def test_on_message_rejects_mq_callback_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="OFTL")

    app.on_message(msg=b"request", cbc=MagicMock(Reason=2033, DataLength=7))

    assert "IBM MQ callback reported reason code 2033" in caplog.messages
    assert not any("Received IBM MQ request message" in message for message in caplog.messages)
