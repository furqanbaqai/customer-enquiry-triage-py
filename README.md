# Customer Enquiry Triage

Python proof of concept that consumes customer enquiries from IBM MQ, starts Temporal workflows,
classifies enquiries through an OpenAI-compatible endpoint, generates product-informed responses,
and publishes response envelopes to IBM MQ.

## Runtime

Run two processes: CLIENT consumes requests and submits workflows; WORKER executes parsing,
classification, generation, and publication activities on `CUSTOMER.ENQUIRY.REQUEST`.
The active workflow is `CustomerEnquiryOrchaestrator` in `CustomerEnquiryOrchestrator_v2.py`.
This Temporal workflow is the sole enquiry orchestration implementation.

The client validates UTF-8 JSON against the bundled request schema, including email/date-time
formats, then uses `start_workflow`. It waits for start acceptance, not processing completion.
Each submission creates a fresh Temporal client/event loop. IDs are
`CE-{channel.upper()}-{refNumber}`. The configurable reuse policy defaults to `ALLOW_DUPLICATE`;
other accepted names are `ALLOW_DUPLICATE_FAILED_ONLY`, `REJECT_DUPLICATE`, and
`TERMINATE_IF_RUNNING`. Names are trimmed and case-insensitive.

Client timeouts are 30 seconds for connection, 60 seconds for the start RPC, 25 minutes for
workflow execution, and 10 seconds for a workflow task. The worker connects once, registers
four activities, limits concurrent activities to two, and configures ten minutes for graceful
shutdown. WORKER mode requires MQ settings and closes its result adapter on exit.

## Prerequisites

Prepare the following before running CLIENT and WORKER:

| Prerequisite | Required setup |
| --- | --- |
| Python | Python 3.12 or newer; `.python-version` selects Python 3.13. |
| uv | Install the `uv` package/environment manager and run commands from the project directory. |
| Python libraries | Run `uv sync --dev` to install the dependencies from `uv.lock`, including the required `temporalio` and `ibmmq` libraries. |
| IBM MQ client | Install the IBM MQ C client runtime and SDK components needed by the `ibmmq` Python adapter on each application host. |
| IBM MQ service | Provide a reachable queue manager, listener, channel, credentials, and request/result queues. CLIENT needs permission to read requests; WORKER needs permission to publish results. Configure the `OFTL_IMQ_*` settings. |
| Temporal service | Provide a running Temporal server reachable by both processes through `OFTL_AI_TEMPORALURL` (default `localhost:7233`). Installing `temporalio` installs the Python SDK; the Temporal server must run separately. The current connection code uses the default namespace and does not configure TLS or API-key authentication. |
| AI endpoint | Provide a reachable OpenAI-compatible Chat Completions endpoint and token through `OFTL_OPENAI_URL` and `OFTL_OPENAI_APITOKEN`. The application sends model name `default`. |
| Prompt and product files | Supply compatible templates through `OFTL_AI_PROMPT_1` and `OFTL_AI_PROMPT_2`, and retain the `prompts/product_json/` catalogue. See the prompt compatibility note below before using `.env.example`. |
| Application configuration | Create `.env` from `.env.example` and replace example values. Run both CLIENT and WORKER for end-to-end processing. |

The runtime Python dependencies declared in [pyproject.toml](pyproject.toml) are:

| Library | Declared minimum | Purpose |
| --- | --- | --- |
| `temporalio` | `1.32.0` | Temporal clients, workers, workflows, activities, and retry policies. |
| `ibmmq` | `2.1.0` | IBM MQ request consumption and response publication. |
| `openai` | `3.3.1` | Calls to the OpenAI-compatible AI endpoint. |
| `jsonschema` | `4.23.0` | Request schema validation. |
| `rfc3339-validator` | `0.1.4` | Date-time format validation. |
| `python-dotenv` | `1.2.3` | Loading `.env` configuration. |
| `lingua-language-detector` | `2.2.0` | Language detection utility. |
| `environs` | `15.1.0` | Declared configuration dependency; the current loader uses `python-dotenv`. |
| `sqlalchemy` | `2.0.52` | Declared persistence dependency; database persistence is not implemented. |

`uv.lock` records the resolved versions. The development group additionally installs `pytest`,
`pytest-cov`, `ruff`, `mypy`, and `types-jsonschema`. SQL Server is not required by the current
runtime because no database operations are implemented.

## Temporal Python library

The application uses [`temporalio`](https://github.com/temporalio/sdk-python), the official
Temporal Python SDK, to submit workflows, host workers, define workflows and activities,
and configure retries and timeouts. The dependency is declared as `temporalio>=1.32.0` in
[pyproject.toml](pyproject.toml); `uv sync --dev` installs the version resolved in `uv.lock`.
A running Temporal service is required separately from the Python library.

References:

- [Python SDK source and usage guide](https://github.com/temporalio/sdk-python)
- [Python SDK API reference](https://python.temporal.io/)
- [Python application development guide](https://docs.temporal.io/develop/python)
- [temporalio package on PyPI](https://pypi.org/project/temporalio/)

## Quick start

Complete the prerequisites above, then install dependencies and configure the application:

```powershell
uv sync --dev
Copy-Item .env.example .env
# Configure MQ, Temporal, AI, and prompt settings before starting.
uv run python -m src CLIENT
# In a second terminal:
uv run python -m src WORKER
```

Installed commands are `customer-enquiry-triage CLIENT`, `customer-enquiry-triage WORKER`,
`customer-enquiry-triage-client`, and `customer-enquiry-triage-worker` (run through `uv run`).
Python callers can use `main("CLIENT")` or `main("WORKER")`.

## Configuration

Process environment overrides `.env`. AI endpoint and prompt settings are required for active
worker processing. MQ settings are required in both modes. Configuration is not comprehensively
validated at startup; AI and prompt validation occurs when used.

| Variable | Required | Default or example |
| --- | --- | --- |
| `OFTL_AI_TEMPORALURL` | No | `localhost:7233` |
| `OFTL_AI_TEMPORALREUSE_POLICY` | No | `ALLOW_DUPLICATE` |
| `OFTL_OPENAI_URL` | Yes | OpenAI-compatible base or `/chat/completions` URL |
| `OFTL_OPENAI_APITOKEN` | Yes | No default |
| `OFTL_OPENAI_TEMPERATURE` | No | `0.1` |
| `OFTL_OPENAI_TOP_P` | No | `0.9` |
| `OFTL_OPENAI_MAX_TOKENS` | No | `200` |
| `OFTL_OPENAI_TIMEOUT` | No | `300` seconds |
| `OFTL_OPENAI_STREAM` | No | `False` |
| `OFTL_AI_PROMPT_1` | Yes | `prompts/customer_enquiry_triage.md` |
| `OFTL_AI_PROMPT_2` | Yes | `prompts/message-generation/enquiry-message-generator-v1.0.md` |
| `OFTL_IMQ_QMGR` | Yes | No default |
| `OFTL_IMQ_CHANNEL` | Yes | No default |
| `OFTL_IMQ_LISTENER` | Yes | `1414` in `.env.example` |
| `OFTL_IMQ_USERNAME` | Yes | No default |
| `OFTL_IMQ_PASS` | Yes | No default |
| `OFTL_IMQ_HOST` | Yes | No default |
| `OFTL_IMQ_REQUEST_QUEUE` | No | `AI.CUST.ENQ.TRIAGE.REQUEST.Q` |
| `OFTL_IMQ_RESULT_QUEUE` | No | `AI.CUST.ENQ.TRIAGE.RESULT.Q` |
| `OFTL_IMQ_BACKOUT_QUEUE` | No | `AI.CUST.ENQ.TRIAGE.BACKOUT.Q` (reserved; unused) |
| `OFTL_LOG_LEVEL` | No | `INFO` |
| `OFTL_LOG_FORMAT` | No | See `.env.example` |

See [`.env.example`](.env.example) for the complete configuration. Never commit `.env` or real
credentials.

## Prompts and product information

Classification supplies `MESSAGE` and `CATEGORY`. Generation supplies `INPUT_MESSAGE`,
`INPUT_EMOTION`, and `PRODUCT_INFORMATION`. The classifier output must contain `emotionalType`
and `product_code`; the generator loads `prompts/product_json/{product_code}.json` and supplies
its JSON content to the response template. The catalogue contains 99 files; no vector retrieval
is implemented. Templates are cached by resolved path per loader.

The unversioned classification template selected by `.env.example` expects additional placeholders
that the active classifier does not supply. Select a compatible template before running; the
example currently fails prompt rendering. Product codes and AI output shapes need stronger
validation. OpenAIUtility currently validates only that the response is a JSON object.

## Outcomes and retries

Success publishes response code `0000`. Terminal processing activity failures publish an error
with the original decoded request and any partial results, then fail the workflow with a
non-retryable ApplicationError.

| Stage | Per-attempt timeout | Total budget | Error code |
| --- | --- | --- | --- |
| Parsing | 30 seconds | 2 minutes | `8100` |
| Classification | 5 minutes | 9 minutes | `8200` |
| Generation | 5 minutes | 9 minutes | `8300` |
| Publication | 30 seconds | 3 minutes | No recursive publication |

Each policy allows up to five attempts, with exponential backoff from two to ten seconds.
Input validation errors in the parser are non-retryable; schema I/O failures remain retryable.
The activity parser does not enforce formats as the client does. Client validation failures occur
before workflow creation and only get logged by the MQ callback.

Unexpected exceptions in workflow processing publish `9999`. Cancellation propagates without
business-error publication. Publishing failures are not recursively published. Termination and
execution timeout cannot be handled through this publication path. Existing executions retain
their original timeout; replay-check histories or drain executions before incompatible rollout.

Response wire keys retain their existing spellings: `meta`, `orignalMessage`, `aiAssesment`,
and `aiGeneratedResponse`. Response codes/descriptions go in metadata; absent partial results
are omitted. Even errors without a decoded request have response metadata.

## Logging and delivery limitations

Use `workflow.logger` inside workflows, `activity.logger` inside activities, and the application
Logging utility elsewhere. These are worker logs; no custom portal logging or activity heartbeat
implementation exists. Workflow history records activity outcomes. OpenAI INFO logging includes
timing and available token usage. DEBUG logging currently includes prompts, AI responses, and
MQ settings containing credentials; this remains an unresolved logging issue.

MQGET removes requests without a transaction before validation and Temporal acceptance. Callback
failures can lose requests; ambiguous result puts can cause duplicates. There is no SQL persistence,
backout handling, durable application backlog, or application-level deduplication. The single
submission executor has an unbounded backlog. The shared MQ publisher has no concurrency guard.

## Development and current validation

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
```

Validation on 2026-09-11 after removing the legacy orchestrator and migrating its tests:
118 tests passed with 87% branch-inclusive coverage. Ruff lint, formatting, and strict mypy checks
pass. Tests cover the active parser, workflow sequencing and retry budgets, product-informed
generation, submission policies, and error publication. No live integration services were used.

On this Windows environment, sandboxed pytest runs encounter temporary-directory access errors;
the passing suite ran outside the sandbox with a fresh explicit `--basetemp` directory.
See [AGENTS.MD](AGENTS.MD) for architecture, remaining gaps, and development instructions.

## Project structure

```text
src/application/     Temporal client, worker, workflow, activities, request schema
src/config/          Environment configuration
src/infrastructure/  IBM MQ adapter
src/utilities/       Logging, prompt, OpenAI, and response helpers
prompts/             Templates and product JSON catalogue
tests/               Unit tests; integration package currently empty
```

## License

Licensed under the [Apache License 2.0](LICENSE).
