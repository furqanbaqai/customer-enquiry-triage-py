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
| Prompt and product files | Supply compatible templates through `OFTL_AI_PROMPT_1` and `OFTL_AI_PROMPT_2`, and retain the `prompts/product_json/` catalogue. See the prompt configuration details below. |
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
uv run customer-enquiry-triage-client
# In a second terminal:
uv run customer-enquiry-triage-worker
```

Use the installed `customer-enquiry-triage-client` and `customer-enquiry-triage-worker` commands
through `uv run`. The generic command currently does not parse positional mode arguments.
Python callers can use `main("CLIENT")` or `main("WORKER")`.

## Docker build

Start Docker Desktop with the Linux container engine running. The build requires access to
`dhi.io` for the base images and to the configured Python package index for dependencies.

1. Keep the IBM MQ redistributable archive at:
   `C:\Users\baqai\source\sib\poc-slm-py\binaries\10.0.0.5-IBM-MQC-Redist-LinuxX64.tar.gz`.
2. Open PowerShell in the application directory containing [Dockerfile](Dockerfile).
3. Build the image with the required `mq-binaries` named context:

```powershell
Set-Location 'C:\Users\baqai\source\sib\poc-slm-py\customer-enquiry-triage-py'
docker build --build-context "mq-binaries=C:\Users\baqai\source\sib\poc-slm-py\binaries" --file Dockerfile --tag customer-enquiry-triage:0.1.0 .
```

When the application and `binaries` directories are siblings, this relative-path command is
equivalent when run from the application directory:

```powershell
docker build --build-context mq-binaries=../binaries --file Dockerfile --tag customer-enquiry-triage:0.1.0 .
```

The named context must point to the **directory containing the archive**, not the archive itself.
The Dockerfile reads the archive using `COPY --from=mq-binaries`, extracts it in the builder,
and copies the MQ client into the runtime image. `--file` selects the Dockerfile, `--tag` names
the image, and the final `.` supplies the application directory as the main build context.

### Troubleshooting build contexts

- **`pull access denied` for `docker.io/library/mq-binaries:latest`:** the command omitted
  `--build-context mq-binaries=...`. Docker interprets the unresolved name as a container image.
  Run either complete command above; a Docker Hub login does not fix the missing context.
- **MQ archive not found:** confirm the named context directory contains the exact archive name
  shown above. `ADD ../binaries/...` cannot read outside the main build context.
- **Cannot resolve or download from `dhi.io`:** check Docker Desktop's network/VPN connectivity
  and registry access. If a proxy is required, configure Docker Desktop's proxy settings.

References: [Docker build command](https://docs.docker.com/reference/cli/docker/buildx/build/)
and [Docker build contexts](https://docs.docker.com/build/concepts/context/).

### Current build status

The Dockerfile defaults to `dhi.io/python:3.13-debian13-dev` for the builder and
`dhi.io/python:3.13-debian13` for the runtime. Their names can be changed using the
`DOCKER_PYTHON_BUILDER_IMAGE` and `DOCKER_PYTHON_RUNTIME_IMAGE` build arguments.
It uses BuildKit's bundled frontend, avoiding a separate Docker Hub frontend download.
The `.dockerignore` allowlist excludes `.env`, `.venv`, `.git`, and local artifacts from
the application context.

The Dockerfile uses matching Python 3.13 Debian 13 stages, disables uv Python downloads,
and installs locked runtime dependencies with the image's `/usr/bin/python3`. The virtual
environment, MQ libraries, source, metadata, and prompts are copied into the runtime with
read/traverse permissions for user 65532. No uv synchronization or package downloads occur
at startup. Keep both base-image overrides on matching Python versions and distributions.

The rebuild attempted on 2026-09-12 was blocked while downloading base-image metadata because
Docker Desktop could not resolve `production.cloudfront.docker.com`. No replacement image was
produced; full build and runtime verification remain pending network recovery.

### Select the container mode

Set `OFTL_RUN_MODE` when starting the container. It accepts `WORKER` or `CLIENT` and defaults
to `WORKER`. Rebuild the image after changing the Dockerfile, then run the modes as separate
containers:

```powershell
docker run --rm --name enquiry-worker --env-file .env -e OFTL_RUN_MODE=WORKER customer-enquiry-triage:0.1.0
docker run --rm --name enquiry-client --env-file .env -e OFTL_RUN_MODE=CLIENT customer-enquiry-triage:0.1.0
```

Run these commands in separate terminals. The Docker CMD reads the environment variable and
passes it explicitly to `src.app.main(mode)`; an empty or unsupported value fails launcher
validation. Native Python commands continue to use an explicit `CLIENT` or `WORKER` argument.
Configure MQ, Temporal, and AI addresses in `.env` to be reachable from the containers;
`localhost` inside a container refers to that container. The application runs in the container's Python process without an intermediate shell or uv process.

## Configuration

[.env.example](.env.example) lists every application `OFTL_*` setting. Copy it to `.env` and
replace the placeholders. Its service addresses target Docker Desktop containers connecting
to services on the Windows host (`host.docker.internal`). For native execution use `localhost`;
for remote services use their actual hostname. The examples are not production credentials.

ConfigLoader reads the project-root `.env` and overlays process environment values. Docker
`--env-file .env` supplies process variables; explicit `-e OFTL_RUN_MODE=CLIENT` overrides that
file's mode. Keep values on separate `KEY=value` lines without inline comments or shell expansion.
Defaults below apply when a key is absent; a blank value does not automatically select a default.

### Startup and Temporal

| Variable | Used by | Default | Accepted value / purpose |
| --- | --- | --- | --- |
| `OFTL_RUN_MODE` | Docker launcher; application startup | `WORKER` in Docker | Exact `CLIENT` or `WORKER`; Docker rejects empty/other values. |
| `OFTL_AI_TEMPORALURL` | Both modes | `localhost:7233` | Non-empty Temporal host:port; example `host.docker.internal:7233`. |
| `OFTL_AI_TEMPORALREUSE_POLICY` | CLIENT | `ALLOW_DUPLICATE` | `ALLOW_DUPLICATE`, `ALLOW_DUPLICATE_FAILED_ONLY`, `REJECT_DUPLICATE`, or `TERMINATE_IF_RUNNING`; whitespace trimmed, case-insensitive. |

The current application has a separate native-startup issue: `main()` uses bitwise `|` in its
mode fallback expression. Docker bypasses that expression by passing the mode explicitly.
For native execution, use the installed `customer-enquiry-triage-client` or
`customer-enquiry-triage-worker` commands, which also pass an explicit mode. Setting the
variable alone does not fix native `main()` until that expression is corrected.

Temporal namespace, TLS, API key, task queue, and workflow/activity timeouts are not exposed as
application environment settings. The current connection uses the default namespace, and the
task queue is `CUSTOMER.ENQUIRY.REQUEST`. Do not add speculative keys to `.env` expecting them
to change these settings.

### IBM MQ

All six connection fields are required at startup in both modes, even when a mode uses only
one queue. The example values below are placeholders, not code defaults.

| Variable | Required / default | Meaning |
| --- | --- | --- |
| `OFTL_IMQ_QMGR` | Required; example `QM1` | Queue manager name. |
| `OFTL_IMQ_CHANNEL` | Required; example `DEV.APP.SVRCONN` | Client connection channel. |
| `OFTL_IMQ_LISTENER` | Required; example `1414` | Integer port, 1–65535; no code default. |
| `OFTL_IMQ_USERNAME` | Required; example `app` | MQ username. |
| `OFTL_IMQ_PASS` | Required; `replace-me` | MQ password; replace with the actual credential. |
| `OFTL_IMQ_HOST` | Required; example `host.docker.internal` | Hostname or IP without a scheme or port. |
| `OFTL_IMQ_REQUEST_QUEUE` | `AI.CUST.ENQ.TRIAGE.REQUEST.Q` | CLIENT input queue. |
| `OFTL_IMQ_RESULT_QUEUE` | `AI.CUST.ENQ.TRIAGE.RESULT.Q` | WORKER output queue. |
| `OFTL_IMQ_BACKOUT_QUEUE` | `AI.CUST.ENQ.TRIAGE.BACKOUT.Q` | Reserved; no backout publication is implemented. |

### AI processing and prompts

These settings apply to WORKER processing, and are validated when used rather than fully at
startup. CLIENT does not call the AI endpoint.

| Variable | Required / default | Accepted value / purpose |
| --- | --- | --- |
| `OFTL_OPENAI_URL` | Required | OpenAI-compatible base URL or full `/chat/completions` URL. |
| `OFTL_OPENAI_APITOKEN` | Required | Non-empty API token. |
| `OFTL_OPENAI_TEMPERATURE` | `0.1` | Number from 0 to 2. |
| `OFTL_OPENAI_TOP_P` | `0.9` | Number from 0 to 1. |
| `OFTL_OPENAI_MAX_TOKENS` | `200` | Integer >= 1. |
| `OFTL_OPENAI_TIMEOUT` | `300` | Integer >= 1; HTTP timeout in seconds. |
| `OFTL_OPENAI_STREAM` | `False` | `true` or `false`, case-insensitive; no numeric/yes/no aliases. |
| `OFTL_AI_PROMPT_1` | Required; example `prompts/customer_enquiry_triage_v04.md` | Classification template; no code default path. |
| `OFTL_AI_PROMPT_2` | Required; example `prompts/message-generation/enquiry-message-generator-v1.0.md` | Response-generation template; no code default path. |

The model name is fixed as `default`; no model environment variable is implemented. Product
JSON comes from `prompts/product_json/`, also not an environment-configurable path.

### Logging

| Variable | Default | Meaning |
| --- | --- | --- |
| `OFTL_LOG_LEVEL` | `INFO` | Standard logging level, case-insensitive; unknown names fall back to INFO. |
| `OFTL_LOG_FORMAT` | See `.env.example` | Python logging format; the example exactly matches the code default. |

Current DEBUG logs may contain MQ credentials, prompts, and AI responses. Temporal failure
tracebacks include SDK/server exception details. Never commit real credentials or customer data.
`ConfigLoader.decrypt` is a placeholder, including for variables ending in `_SECRET`.

### Docker-managed settings

The Dockerfile sets `APP_HOME`, `VIRTUAL_ENV`, `PATH`, `MQ_INSTALLATION_PATH`, `LD_LIBRARY_PATH`,
`PYTHONDONTWRITEBYTECODE`, and `PYTHONUNBUFFERED`. Its builder also sets `UV_PYTHON_DOWNLOADS`,
`UV_LINK_MODE`, and `PIP_NO_CACHE_DIR`. These image settings do not need entries in `.env.example`.
`DOCKER_PYTHON_BUILDER_IMAGE` and `DOCKER_PYTHON_RUNTIME_IMAGE` are build arguments, supplied
through `docker build --build-arg`, not runtime application settings.

## Prompts and product information

Classification supplies `MESSAGE` and `CATEGORY`. Generation supplies `INPUT_MESSAGE`,
`INPUT_EMOTION`, and `PRODUCT_INFORMATION`. The classifier output must contain `emotionalType`
and `product_code`; the generator loads `prompts/product_json/{product_code}.json` and supplies
its JSON content to the response template. The catalogue contains 99 files; no vector retrieval
is implemented. Templates are cached by resolved path per loader.

The example selects classification v04, whose placeholders match the active classifier.
The unversioned template requires additional placeholders and is not compatible with that caller. Product codes and AI output shapes need stronger
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

### Temporal submission diagnostics

Failed Temporal submissions log the stage (`connect` or `start`), workflow ID, task queue,
reuse policy, exception type/message, and full traceback with chained causes. The wrapper
RuntimeError retains the original cause. The request payload is not explicitly logged;
exception text can contain details supplied by the SDK/server. Use the stage and traceback
to distinguish connection configuration failures from workflow-start rejection.
