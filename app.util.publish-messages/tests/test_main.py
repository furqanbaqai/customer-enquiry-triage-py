"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Verify CSV conversion, startup, and fail-fast MQ publication without live services.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main


@pytest.fixture
def environment() -> dict[str, str]:
    return {
        "OFTL_SOURCE_CSV_FILE": "input.csv",
        "OFTL_IMQ_HOST": "localhost",
        "OFTL_IMQ_LISTENER": "1414",
        "OFTL_IMQ_CHANNEL": "DEV.APP.SVRCONN",
        "OFTL_IMQ_REQUEST_QUEUE": "REQUEST.Q",
        "OFTL_IMQ_USERNAME": " ",
        "OFTL_IMQ_PASS": " ",
    }


@pytest.fixture
def row() -> dict[str, str]:
    return dict(
        zip(
            main.COLUMNS,
            [
                "Enquiry",
                "Zoë",
                "Example",
                "zoe@example.test",
                "00123456789",
                "Savings",
                'Hello,\n"world"',
                "false",
            ],
            strict=True,
        )
    )


def write_csv(path: Path, row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=main.COLUMNS)
        writer.writeheader()
        writer.writerow(row)


def test_settings(environment: dict[str, str]) -> None:
    settings = main.Settings.from_environment(environment)
    assert settings.username == ""
    assert settings.queue_manager == ""
    environment["OFTL_IMQ_PASS"] = "secret-value"
    assert "secret-value" not in repr(main.Settings.from_environment(environment))


@pytest.mark.parametrize("port", ["", "bad", "0", "65536"])
def test_invalid_port(environment: dict[str, str], port: str) -> None:
    environment["OFTL_IMQ_LISTENER"] = port
    with pytest.raises(main.UtilityError):
        main.Settings.from_environment(environment)


def test_missing_settings() -> None:
    with pytest.raises(main.UtilityError, match="OFTL_SOURCE_CSV_FILE"):
        main.Settings.from_environment({})


def test_csv_preserves_strings(tmp_path: Path, row: dict[str, str]) -> None:
    path = tmp_path / "input.csv"
    write_csv(path, row)
    assert main.read_rows(path) == [row]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "Message\nHi\n",
        ",".join(main.COLUMNS) + "\nshort,row\n",
        ",".join(main.COLUMNS) + '\n"unterminated',
        ",".join(["Message"] * 8),
    ],
)
def test_invalid_csv(tmp_path: Path, content: str) -> None:
    path = tmp_path / "input.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(main.UtilityError):
        main.read_rows(path)


def test_missing_csv(tmp_path: Path) -> None:
    with pytest.raises(main.UtilityError, match="Cannot read"):
        main.read_rows(tmp_path / "missing.csv")


def test_envelope_and_reference_collision(row: dict[str, str]) -> None:
    builder = main.MessageBuilder()
    now = datetime(2026, 9, 19, 8, 0, 0, 123456, tzinfo=UTC)
    message = builder.build(row, now)
    assert message == {
        "meta": {
            "refNumber": "ENQ-2026-0919080000123456",
            "channel": "WBST",
            "reqIssuedAt": "2026-09-19T08:00:00Z",
        },
        "receivedAt": "2026-09-19T08:00:00Z",
        "mobileNumber": "00123456789",
        "firstName": "Zoë",
        "lastName": "Example",
        "emailAddress": "zoe@example.test",
        "message": 'Hello,\n"world"',
        "category": "Savings",
    }
    assert builder.build(row, now)["meta"] != message["meta"]
    with pytest.raises(ValueError, match="timezone-aware"):
        builder.build(row, now.replace(tzinfo=None))


def test_publish_stops_at_first_failure(row: dict[str, str]) -> None:
    publisher = Mock()
    publisher.publish.side_effect = [None, main.UtilityError("put failed"), None]
    with pytest.raises(main.UtilityError, match="row 2; 1 prior"):
        main.publish_rows([row, row, row], publisher)
    assert publisher.publish.call_count == 2
    payload = publisher.publish.call_args_list[0].args[0]
    assert isinstance(payload, bytes)
    assert json.loads(payload)["firstName"] == "Zoë"


@pytest.fixture
def mq(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    class MQError(Exception):
        pass

    constants = SimpleNamespace(
        **{
            name: 1 << index
            for index, name in enumerate(
                [
                    "MQFMT_STRING",
                    "MQPER_PERSISTENT",
                    "MQPMO_NO_SYNCPOINT",
                    "MQPMO_FAIL_IF_QUIESCING",
                    "MQOO_OUTPUT",
                    "MQOO_FAIL_IF_QUIESCING",
                ]
            )
        }
    )
    module = SimpleNamespace(
        connect=Mock(),
        Queue=Mock(),
        MD=Mock(side_effect=SimpleNamespace),
        PMO=Mock(side_effect=SimpleNamespace),
        CMQC=constants,
        MQMIError=MQError,
    )
    monkeypatch.setitem(sys.modules, "ibmmq", module)
    return module


@pytest.mark.parametrize("failure", [None, "connect", "open", "put", "close"])
def test_mq_lifecycle(
    tmp_path: Path,
    row: dict[str, str],
    environment: dict[str, str],
    mq: SimpleNamespace,
    failure: str | None,
) -> None:
    path = tmp_path / "input.csv"
    write_csv(path, row)
    environment["OFTL_SOURCE_CSV_FILE"] = str(path)
    if failure is not None:
        operation = {
            "connect": mq.connect,
            "open": mq.Queue,
            "put": mq.Queue.return_value.put,
            "close": mq.Queue.return_value.close,
        }[failure]
        operation.side_effect = mq.MQMIError("sensitive vendor detail")
        with pytest.raises(main.UtilityError) as caught:
            main.run(main.Settings.from_environment(environment))
        assert "sensitive vendor detail" not in str(caught.value)
    else:
        assert main.run(main.Settings.from_environment(environment)) == 1
        args = mq.Queue.return_value.put.call_args.args
        assert args[1].CodedCharSetId == 1208
        assert args[1].Persistence == mq.CMQC.MQPER_PERSISTENT
        assert args[2].Options & mq.CMQC.MQPMO_NO_SYNCPOINT
        assert mq.Queue.call_args.args[1] == "REQUEST.Q"
        mq.connect.assert_called_once_with(
            "",
            "DEV.APP.SVRCONN",
            "localhost(1414)",
            user=None,
            password=None,
        )
    if failure not in ("connect", "open"):
        mq.Queue.return_value.close.assert_called_once()
    if failure != "connect":
        mq.connect.return_value.disconnect.assert_called_once()


def test_env_loads_all_variables_and_preserves_process_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {"CUSTOM_SETTING": "process"})
    (tmp_path / ".env").write_text("CUSTOM_SETTING=file\nEXTRA_SETTING=loaded\n", encoding="utf-8")
    assert main.main() == 1
    assert os.environ["CUSTOM_SETTING"] == "process"
    assert os.environ["EXTRA_SETTING"] == "loaded"


def test_console_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "load_dotenv", Mock())
    monkeypatch.setattr(main.Settings, "from_environment", Mock())
    runner = Mock(return_value=2)
    monkeypatch.setattr(main, "run", runner)
    assert main.main() == 0
    runner.side_effect = main.UtilityError("failure")
    assert main.main() == 1
    runner.side_effect = KeyboardInterrupt
    assert main.main() == 130
