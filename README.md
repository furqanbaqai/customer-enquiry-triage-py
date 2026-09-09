# Customer Enquiry Triage

Python proof-of-concept service that consumes customer enquiries from IBM MQ and dispatches
them to a worker callback. The callback currently logs receipt and has a placeholder for a
replacement processing library or class. The existing AI orchestrator is no longer invoked
by the service entry point.

## Features

The repository includes the following components; validation, AI processing, and result
publishing require explicitly invoking the existing orchestrator or wiring a replacement handler.

- Asynchronous IBM MQ consumption with worker-isolated processing
- JSON Schema validation for incoming enquiries
- Markdown prompt templates with `{{VARIABLE_NAME}}` substitution
- Configurable OpenAI-compatible Chat Completions client
- Two-stage AI assessment and emotion-aware response generation
- Combined response-envelope publishing to IBM MQ
- Environment-based configuration and structured logging

> [!NOTE]
> SQL Server persistence, backout publishing, duplicate detection, and transactional delivery
> are not implemented. Known failure-handling and shutdown gaps are recorded in
> [AGENTS.MD](AGENTS.MD#context-snapshot-2026-09-06).

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- IBM MQ C client runtime and SDK components
- Access to IBM MQ and an OpenAI-compatible endpoint

## Quick start

```powershell
git clone https://github.com/furqanbaqai/customer-enquiry-triage-py.git
cd customer-enquiry-triage-py
uv sync --dev
Copy-Item .env.example .env
```

Update `.env` with your MQ connection values, then start the service. API and prompt settings
are needed when invoking the existing AI orchestrator:

```powershell
uv run python -m src CLIENT
```

The installed command is equivalent:

```powershell
uv run customer-enquiry-triage CLIENT
```

## Configuration

`CustomerEnquiryClient.sendToWorkflow(payload)` in `src/application/CustomerEnquiryClient.py`
accepts UTF-8 JSON bytes, validates the enquiry schema (including email and date-time formats),
and sends the complete enquiry as a JSON string to the v2 Temporal workflow. Call it from a
synchronous thread; it waits for workflow completion. The MQ callback does not yet invoke it.
`OFTL_AI_TEMPORALURL` is optional and defaults to `localhost:7233`. A Temporal worker must
register `CustomerEnquiryOrchaestrator` from `CustomerEnquiryOrchestrator_v2.py` on task queue
`CUSTOMER.ENQUIRY.REQUEST`. Workflow IDs use `customer-enquiry-<meta.refNumber>` and reject
duplicate executions while Temporal retains their history. Connection and RPC timeouts are
30 seconds, workflow execution is limited to 300 seconds, and the client wait to 330 seconds.
Invalid input raises `ValueError`; schema-loading and Temporal failures raise `RuntimeError`
with the original cause preserved. Logs omit payloads and workflow results. A client timeout
does not guarantee that the server-side workflow has stopped.

The required mode is `CLIENT` or `WORKER`. `CLIENT` starts the IBM MQ consumer.
`uv run python -m src WORKER` starts `CustomerEnquiryWorker` in the current process.
It connects once to `OFTL_AI_TEMPORALURL` (default `localhost:7233`) and polls
`CUSTOMER.ENQUIRY.REQUEST`, registering the v2 `CustomerEnquiryOrchaestrator` workflow and
the bound activities `MessageClassifier.classify_message` and
`MessageGenerator.generate_response_message`. Connection startup has a 30-second timeout.
Press Ctrl+C to stop; the worker context performs shutdown with a 30-second activity grace
period before requesting activity cancellation. The workflow still only echoes its input;
registering the activities does not make the workflow invoke them.
Workflow code uses `workflow.logger` for logging. Importing the application `Logging`
utility loads configuration that calls `Path.resolve()` during import, which Temporal's
sandbox rejects with a workflow validation error.
Python callers can use `main("CLIENT")` or `main("WORKER")`; calling `main()` reads CLI arguments.

The VS Code worker launch sets `TEMPORAL_DEBUG=1` for breakpoint debugging. Server-side
workflow task and activity timeouts still apply while paused. A sandbox warning mentioning
`_pydevd_bundle` indicates a debugger import; inspect subsequent exceptions for task failures.
Use `workflow.logger` inside workflows and `activity.logger` inside activities. Using the
workflow logger in an activity raises `Not in workflow event loop` and can trigger retries.

AI endpoint and prompt requirements below apply to the existing orchestrator, which is
currently disconnected from the message callback.

| Variable | Required | Default or example |
| --- | --- | --- |
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

## Prompt templates

Templates are UTF-8 Markdown files with uppercase placeholders such as `{{MESSAGE}}`. Paths are
resolved from the service working directory. Missing files, blank templates, and unresolved
placeholders fail with a clear error.

Assessment receives `MESSAGE` and `CATEGORY`. Response generation receives `INPUT_MESSAGE`,
`INPUT_EMOTION`, and `PRODUCT_INFORMATION`; the last currently contains the request category,
not a product catalogue lookup. Templates are cached for the lifetime of the prompt loader.

## Development

Run the quality checks before submitting a change:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
```

## Project structure

```text
src/application/     Enquiry orchestration and request schema
src/config/          Environment configuration
src/infrastructure/  IBM MQ adapter
src/utilities/       Logging, prompt, and OpenAI helpers
prompts/             Markdown prompt templates
tests/               Unit and integration tests
```

## Contributing

Open an issue before proposing a substantial change. Keep pull requests focused, add tests for
behavior changes, and ensure the development checks pass.

## License

Licensed under the [Apache License 2.0](LICENSE).
