# Console utility for publishing messages

Console utility that loads customer enquiries from CSV and publishes one UTF-8 JSON
message per row to IBM MQ. Requires Python >=3.12, uv, and the native IBM MQ client
libraries available to `ibmmq` (including the appropriate DLL search path on Windows).

Set up the utility from this directory:

```powershell
uv sync --dev
Copy-Item .env.example .env
# Set OFTL_SOURCE_CSV_FILE and MQ settings in .env before running.
uv run util.publish.mq
```

All variables in `app.util.publish-messages/.env` load into an `environs.Env` instance at
console startup, regardless of the working directory. Other `.env` files are not searched.
Existing process environment values take precedence. `.env` is optional when all settings are supplied by
the process environment. Credentials and message contents are not logged. Keep `.env`
and real customer CSVs out of version control.

For Windows paths containing spaces, use one pair of single quotes in `.env`:

```dotenv
OFTL_SOURCE_CSV_FILE='G:\My Drive\SimulatedData\enquiries.csv'
```

Do not put double quotes inside those single quotes: they become part of the filename
and cause Windows error 22 (`Invalid argument`). If `uv` warns that `VIRTUAL_ENV`
points to the parent project's environment, run `deactivate` before running the utility
from this directory; `uv run` will use this utility's own `.venv`.

| Variable | Meaning |
| --- | --- |
| `OFTL_SOURCE_CSV_FILE` | Required UTF-8 CSV path; relative to the current working directory. |
| `OFTL_IMQ_HOST` | Required MQ server host. |
| `OFTL_IMQ_LISTENER` | Required listener port, 1–65535. |
| `OFTL_IMQ_CHANNEL` | Required server connection channel, e.g. `DEV.APP.SVRCONN`. |
| `OFTL_IMQ_REQUEST_QUEUE` | Required destination queue name. |
| `OFTL_IMQ_USERNAME` | Required setting; blank or whitespace means no credentials are supplied. |
| `OFTL_IMQ_PASS` | Required setting; password whitespace is preserved when a username is supplied. |
| `OFTL_IMQ_QMGR` | Optional queue manager name; defaults to blank, selecting the manager at the endpoint. |

The CSV must have these eight unique headers (order may vary):

```csv
Nature Of Request,First Name,Last Name,Email Address,Mobile Number,Category Type,Message,isComplaint
Enquiry,Example,Customer,customer@example.test,00123456789,Savings,Please explain savings accounts,false
```

UTF-8 BOMs, quoted commas, and quoted multiline messages are supported. All fields stay
strings, preserving leading zeros in phone numbers. The entire file is validated for
headers, CSV syntax, row width, and nonempty messages before MQ is connected; it is held
in memory. `Nature Of Request` and `isComplaint` are required input columns but are omitted
from the requested output. The other six columns map to `firstName`, `lastName`,
`emailAddress`, `mobileNumber`, `category`, and `message`.

`meta.channel` is always `WBST`. Both `meta.reqIssuedAt` and `receivedAt` use the current
UTC time, formatted as `2026-09-19T08:00:00Z`. References use
`ENQ-YYYY-MMDDHHmmssffffff`: the six fractional digits are microseconds, matching the
requested six `S` characters. Repeated or backward clock readings advance the reference
timestamp by one microsecond to prevent collisions within a run. References are not a
cross-process deduplication guarantee.

Publication uses `OFTL_IMQ_REQUEST_QUEUE`; `OFTL_IMQ_CHANNEL` configures the connection.
Messages are persistent, marked as MQ string format with UTF-8 CCSID 1208, and put
without syncpoint. On the first put failure the utility stops, reports the data-row index
and prior successful count, closes resources, and exits 1. Previously successful puts
remain on MQ. Delivery of a failed put can be uncertain; there are no automatic retries,
resume checkpoints, or deduplication. Rerunning a file can duplicate earlier messages.
Connection, input, configuration, or cleanup failures also exit 1; success exits 0 and
Ctrl+C exits 130. MQ network-call timeouts are governed by the native client configuration.

Integration limitation: the root triage request schema currently does not accept `WBST`.
This utility follows the requested wire format; the root consumer needs a coordinated
schema change before it can process these messages. Content validation against that root
schema is intentionally not applied here.

The adapter follows IBM's [Python MQ request example](https://github.com/ibm-messaging/mq-dev-patterns/blob/master/Python/basicrequest.py).

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q
uv build
```

Tests use mocked MQ connections and never publish live messages.
