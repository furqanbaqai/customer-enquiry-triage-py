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


def test_main_starts_async_consumer(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="OFTL")
    client = MagicMock()
    wait_event = MagicMock()
    wait_event.wait.side_effect = KeyboardInterrupt
    monkeypatch.setattr(app, "IBMMQClient", MagicMock(return_value=client))
    monkeypatch.setattr(app, "Event", MagicMock(return_value=wait_event))

    app.main()

    client.start_consumer.assert_called_once()
    callback = client.start_consumer.call_args.args[0]
    callback(msg=b"customer request", cbc=MagicMock(Reason=0, DataLength=8))
    assert "Customer enquiry triage service is consuming IBM MQ requests." in caplog.messages
    assert "Received IBM MQ request message (8 bytes)." in caplog.messages
    client.close.assert_called_once_with()
