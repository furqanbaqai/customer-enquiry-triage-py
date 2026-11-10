"""
Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
Licenses: LICENSE.md
Description: Command-line entry point for the MQ publishing utility.
Reference: https://github.com/furqanbaqai/customer-enquiry-triage-py
"""

import csv
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from environs import Env

LOGGER = logging.getLogger(__name__)
PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
ENVIRONMENT_KEYS = (
    "OFTL_SOURCE_CSV_FILE",
    "OFTL_IMQ_HOST",
    "OFTL_IMQ_LISTENER",
    "OFTL_IMQ_CHANNEL",
    "OFTL_IMQ_REQUEST_QUEUE",
    "OFTL_IMQ_USERNAME",
    "OFTL_IMQ_PASS",
    "OFTL_IMQ_QMGR",
)
COLUMNS = (
    "Nature Of Request",
    "First Name",
    "Last Name",
    "Email Address",
    "Mobile Number",
    "Category Type",
    "Message",
    "isComplaint",
)
FIELDS = {
    "mobileNumber": "Mobile Number",
    "firstName": "First Name",
    "lastName": "Last Name",
    "emailAddress": "Email Address",
    "message": "Message",
    "category": "Category Type",
}


class UtilityError(Exception):
    """A configuration, input, or MQ operation prevented publication."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings; credentials are excluded from representations."""

    source: Path
    host: str
    port: int
    channel: str
    queue: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    queue_manager: str = ""

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "Settings":
        required = (
            "OFTL_SOURCE_CSV_FILE",
            "OFTL_IMQ_HOST",
            "OFTL_IMQ_LISTENER",
            "OFTL_IMQ_CHANNEL",
            "OFTL_IMQ_REQUEST_QUEUE",
        )
        missing = [key for key in required if not environment.get(key, "").strip()]
        missing += [key for key in ("OFTL_IMQ_USERNAME", "OFTL_IMQ_PASS") if key not in environment]
        if missing:
            raise UtilityError(f"Missing environment settings: {', '.join(missing)}")
        try:
            port = int(environment["OFTL_IMQ_LISTENER"])
        except ValueError as exc:
            raise UtilityError("OFTL_IMQ_LISTENER must be an integer between 1 and 65535") from exc
        if not 1 <= port <= 65535:
            raise UtilityError("OFTL_IMQ_LISTENER must be between 1 and 65535")
        return cls(
            source=Path(environment["OFTL_SOURCE_CSV_FILE"]),
            host=environment["OFTL_IMQ_HOST"].strip(),
            port=port,
            channel=environment["OFTL_IMQ_CHANNEL"].strip(),
            queue=environment["OFTL_IMQ_REQUEST_QUEUE"].strip(),
            username=environment["OFTL_IMQ_USERNAME"].strip(),
            password=environment["OFTL_IMQ_PASS"],
            queue_manager=environment.get("OFTL_IMQ_QMGR", "").strip(),
        )


def read_rows(source: Path) -> list[dict[str, str]]:
    """Validate the whole UTF-8 CSV before any MQ side effects."""
    rows: list[dict[str, str]] = []
    try:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, [])
            if len(headers) != len(set(headers)) or set(headers) != set(COLUMNS):
                raise UtilityError(
                    "CSV must contain each of the eight documented columns exactly once"
                )
            for values in reader:
                if len(values) != len(headers):
                    raise UtilityError(
                        f"CSV record ending at line {reader.line_num} has wrong column count"
                    )
                row = dict(zip(headers, values, strict=True))
                if not row["Message"].strip():
                    raise UtilityError(
                        f"CSV record ending at line {reader.line_num} has an empty Message"
                    )
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise UtilityError(
            "Cannot read source CSV; verify path, UTF-8 encoding, and CSV syntax"
        ) from exc
    return rows


class MessageBuilder:
    """Create UTC envelopes with distinct references within this process."""

    def __init__(self) -> None:
        self._last_reference_time: datetime | None = None

    def build(self, row: Mapping[str, str], now: datetime) -> dict[str, object]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Message time must be timezone-aware")
        now = now.astimezone(UTC)
        reference_time = now
        if self._last_reference_time is not None and reference_time <= self._last_reference_time:
            reference_time = self._last_reference_time + timedelta(microseconds=1)
        self._last_reference_time = reference_time
        timestamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        message: dict[str, object] = {
            "meta": {
                "refNumber": reference_time.strftime("ENQ-%Y-%m%d%H%M%S%f"),
                "channel": "WebSite",
                "reqIssuedAt": timestamp,
            },
            "receivedAt": timestamp,
        }
        message.update({key: row[column] for key, column in FIELDS.items()})
        return message


class Publisher(Protocol):
    """Publication boundary for the CSV application."""

    def publish(self, payload: bytes) -> None: ...


def publish_rows(rows: list[dict[str, str]], publisher: Publisher) -> int:
    """Publish sequentially, stopping immediately on the first error."""
    builder = MessageBuilder()
    for index, row in enumerate(rows, start=1):
        message = builder.build(row, datetime.now(UTC))
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            publisher.publish(payload)
        except UtilityError as exc:
            raise UtilityError(
                f"Publication failed at data row {index}; {index - 1} prior messages published. "
                "Delivery of the failing message may be uncertain; no further rows attempted"
            ) from exc
        LOGGER.info("Published data row %d", index)
    return len(rows)


def run(settings: Settings) -> int:
    """Own MQ resources and translate vendor errors without exposing customer data."""
    rows = read_rows(settings.source)
    if not rows:
        LOGGER.info("CSV contains no data rows; nothing to publish")
        return 0
    try:
        import ibmmq  # type: ignore[import-untyped]  # Vendor package has no typing marker.
    except (ImportError, OSError) as exc:
        raise UtilityError("IBM MQ Python package or native MQ client is unavailable") from exc

    class MQPublisher:
        def publish(self, payload: bytes) -> None:
            if queue is None:
                raise UtilityError("IBM MQ queue is not open")
            descriptor = ibmmq.MD()
            descriptor.Format = ibmmq.CMQC.MQFMT_STRING
            descriptor.CodedCharSetId = 1208
            descriptor.Persistence = ibmmq.CMQC.MQPER_PERSISTENT
            options = ibmmq.PMO()
            options.Options = ibmmq.CMQC.MQPMO_NO_SYNCPOINT | ibmmq.CMQC.MQPMO_FAIL_IF_QUIESCING
            try:
                queue.put(payload, descriptor, options)
                LOGGER.info(
                    "Published message with refNumber %s", json.loads(payload)["meta"]["refNumber"]
                )
            except ibmmq.MQMIError as exc:
                raise UtilityError("IBM MQ put failed") from exc

    manager = None
    queue = None
    failed = False
    try:
        manager = ibmmq.connect(
            settings.queue_manager,
            settings.channel,
            f"{settings.host}({settings.port})",
            user=settings.username or None,
            password=settings.password if settings.username else None,
        )
        queue = ibmmq.Queue(
            manager,
            settings.queue,
            ibmmq.CMQC.MQOO_OUTPUT | ibmmq.CMQC.MQOO_FAIL_IF_QUIESCING,
        )
        return publish_rows(rows, MQPublisher())
    except ibmmq.MQMIError as exc:
        failed = True
        raise UtilityError("IBM MQ connection or queue open failed") from exc
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_failed = False
        for resource, method in ((queue, "close"), (manager, "disconnect")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except ibmmq.MQMIError:
                    cleanup_failed = True
                    LOGGER.error("IBM MQ resource cleanup failed")
        if cleanup_failed and not failed:
            raise UtilityError("Messages published, but IBM MQ cleanup failed")


def load_environment() -> Env:
    """Load all utility .env values without searching parent or working directories."""
    environment = Env()
    environment.read_env(PROJECT_DIRECTORY / ".env", recurse=False, override=False)
    return environment


def main() -> int:
    """Load all .env variables at startup; return a conventional console exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        environment = load_environment()
        values = {
            key: value
            for key in ENVIRONMENT_KEYS
            if (value := environment.str(key, default=None)) is not None
        }
        count = run(Settings.from_environment(values))
    except UtilityError as exc:
        LOGGER.error("%s", exc)
        return 1
    except (OSError, UnicodeError):
        LOGGER.error("Cannot load .env; verify file permissions and UTF-8 encoding")
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Interrupted; previously published messages remain on MQ")
        return 130
    LOGGER.info("Completed: %d messages published", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
