import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import app


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
    wait_event.wait.side_effect = KeyboardInterrupt
    monkeypatch.setattr(app, "IBMMQClient", MagicMock(return_value=client))
    monkeypatch.setattr(app, "Event", MagicMock(return_value=wait_event))
    monkeypatch.setattr(app, "ThreadPoolExecutor", MagicMock(return_value=executor))

    app.main()

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
    orchestrator = MagicMock()
    buffer = bytearray(b"first messagetrailing bytes")

    app.dispatch_message(
        executor,
        orchestrator,
        msg=buffer,
        cbc=MagicMock(Reason=0, DataLength=13),
    )
    buffer[:] = b"buffer reused by IBM MQ...."

    submitted = executor.submit.call_args
    assert submitted.kwargs["msg"] == b"first message"
    assert submitted.kwargs["cbc"].DataLength == 13
