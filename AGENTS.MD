# AGENTS.MD

## Purpose and scope

These instructions apply to both projects in this monorepo. Keep this file current when architecture,
tooling, or required validation changes. This snapshot replaces the conflicting September 6-10
runtime notes; the source and tests were updated on 2026-09-11 to remove the unused legacy
orchestrator. The active Temporal workflow and registered names remain unchanged.

The root application is a Python IBM MQ-to-Temporal customer enquiry triage proof of concept.
The active workflow validates requests, classifies them through an OpenAI-compatible endpoint,
generates a product-informed response, and publishes a response envelope to IBM MQ.
SQL persistence, transactional delivery, backout handling, and application-level deduplication
are not implemented.

## Monorepo context (reviewed 2026-11-10)

The Git repository root is `customer-enquiry-triage-py/`, beneath the current workspace
`poc-slm-py/`. Resolve paths below relative to the Git repository root.
There are two independently packaged Python projects:

| Location | Package | Current responsibility |
| --- | --- | --- |
| `.` | `customer-enquiry-triage` 0.1.0 | MQ request consumption, Temporal workflow processing, AI classification/generation, MQ response publication. |
| `app.util.publish-messages/` | `util.publish.mq` 0.1.0 | Console utility that converts CSV rows to request JSON and publishes sequentially to IBM MQ. |

Both require Python >=3.12 and have their own `pyproject.toml`, `uv.lock`, and local `.venv`.
The root uses Hatchling and packages `src`; the utility uses setuptools and packages the
`main` module from its own `src/main.py`. There is no `[tool.uv.workspace]`, cross-project
dependency, or shared runtime package configured. This is a monorepo with separate projects,
not a configured uv workspace. Do not consolidate environments or lockfiles implicitly.

The utility uses `environs.Env` to load all variables from `app.util.publish-messages/.env`
at console startup, independent of the working directory, preserving process-value precedence.
It disables parent-directory .env searching. `OFTL_SOURCE_CSV_FILE` supplies the UTF-8 CSV;
relative CSV paths still resolve against the working directory.
It validates all eight documented CSV columns and record widths before connecting, creates
UTC envelopes with `WBST` and six-digit microsecond reference suffixes, and publishes
persistent UTF-8 MQ string messages to `OFTL_IMQ_REQUEST_QUEUE`. `OFTL_IMQ_CHANNEL` is the
connection channel. Optional `OFTL_IMQ_QMGR` defaults to blank; blank usernames omit credentials.
The first failed put stops processing with exit 1; prior nontransactional puts remain delivered.
No retries, resume state, or cross-run deduplication exist. MQ handles are closed on exit.
Its own README, `.env.example`, and mocked tests document the complete contract.
It does not use the root configuration loader, activities, or MQ adapter. The root response
publisher is separate. The root request schema does not accept `WBST`; a coordinated consumer
schema change is needed for end-to-end use. Do not silently change the requested utility format.

Run dependency, build, and execution commands from the intended project directory.
Root pytest discovery is limited to `tests/`, mypy commands target root `src tests`, and
root coverage measures root `src`. These do not validate the utility. Recursive Ruff commands
can discover nested Python files; the utility now has its own Ruff, strict mypy, and pytest
configuration and development dependencies. Run its `ruff check src tests`,
`ruff format --check src tests`, `mypy src tests`, and `pytest -q` from its directory as well.
The root Dockerfile builds the triage service only. `deployment/podman-compose/` supplies
Temporal infrastructure, not a third application project or a utility deployment.

For utility changes, preserve its independent entry point and packaging, and add relevant
configuration/examples and tests as behavior is implemented. Repository-wide security and
change discipline below apply to both projects; root-specific `src` imports, composition-root,
Temporal, and configuration guidance apply to the triage service unless explicitly adopted.

```powershell
# From the repository root: explicit service entry points
uv sync --dev
uv run customer-enquiry-triage-client
# In another terminal at the repository root:
uv run customer-enquiry-triage-worker

# Utility commands, from its project directory
Set-Location app.util.publish-messages
uv sync
uv run util.publish.mq
uv build
```

The generic root entry points do not parse positional CLIENT/WORKER arguments. Use the
dedicated commands above. `src.app.main("CLIENT")` and `src.app.main("WORKER")` are explicit
Python alternatives; the generic startup also has the fallback bug documented below.
The initial context review inspected source, manifests, documentation, and deployment definitions.
The utility implementation subsequently passed 22 mocked tests, Ruff lint/format checks, and
strict mypy on 2026-11-10. Tests required execution outside the sandbox due to Windows temporary
directory access restrictions. No live MQ publication was exercised. Historical root test
results below remain dated evidence.
The subsequent root regression check on 2026-11-10 found 140 passing tests and four failures
in the existing CLI mode-selection tests (`tests/unit/test_app.py`); strict root mypy also
reports two existing `str | None` argument mismatches in `src/__init__.py` and that test file.
Root lint/format checks passed. The utility wheel and source distribution built successfully.
These root startup issues are outside the utility change; root application source is unchanged.

## Repository map

- `pyproject.toml`, `uv.lock`: root triage package and dependency lock.
- `app.util.publish-messages/`: independent utility project with its own manifest and lock.
- `app.util.publish-messages/src/main.py`: CSV loading, envelope conversion, MQ adapter, console entry.
- `app.util.publish-messages/tests/`: independent mocked utility tests.
- `src/app.py`: composition root, CLIENT/WORKER mode selection, MQ callback and shutdown.
- `src/application/CustomerEnquiryClient.py`: synchronous validation and Temporal submission.
- `src/application/CustomerEnquiryOrchestrator_v2.py`: active Temporal workflow, with class spelling
  `CustomerEnquiryOrchaestrator`. Preserve registered workflow/activity names for existing histories.
- `src/application/CustomerEnquiryWorker.py`: registers the active workflow and four activities.
- `src/application/activities/`: parser, classifier, generator, and response publisher.
- `src/application/schema/enquiry-request-v1.0.json`: active request schema.
- `src/infrastructure/ibm_mq.py`: MQ settings, polling, and separate result connection.
- `src/utilities/`: logging, prompt loading, OpenAI calls, response envelope, language utility.
- `src/config/`: process environment overrides project `.env`; decrypt is a placeholder.
- `prompts/`: classification templates through v05, response template, 99 product JSON files.
- `src/domain/` and `tests/integration/`: package initializers only; no persistence implementation.

## Current runtime behavior

1. Run CLIENT and WORKER as separate processes. Both load configuration. CLIENT polls the
   request queue and copies deliveries into a single-thread executor with an unbounded backlog.
2. `on_message` invokes `CustomerEnquiryClient.sendToWorkflow`. Invalid callback reasons and
   submission failures are logged; there is no retry, backout, or error-envelope publication here.
3. The client decodes UTF-8 JSON and performs Draft 2020-12 schema validation with email/date-time
   format checking. It reloads/checks the schema for each message. It requires a synchronous
   caller without an active event loop and creates a fresh loop/client per enquiry.
4. `Client.start_workflow` waits for start acceptance, not workflow completion. Its returned
   handle is logged at DEBUG; no `handle.result()` is awaited. Later workflow failures are
   handled by the workflow, not this callback.
5. Endpoint: `OFTL_AI_TEMPORALURL`, default `localhost:7233`. Task queue:
   `CUSTOMER.ENQUIRY.REQUEST`. ID: `CE-{channel.upper()}-{refNumber}`. Reuse policy comes from
   `OFTL_AI_TEMPORALREUSE_POLICY`, default `ALLOW_DUPLICATE`, trimmed and uppercased for enum
   lookup. Recognized names are ALLOW_DUPLICATE, ALLOW_DUPLICATE_FAILED_ONLY, REJECT_DUPLICATE,
   and TERMINATE_IF_RUNNING. No explicit ID conflict policy or UTF-8 byte-length check exists.
   Schema refNumber length is 1-36 characters and channel is restricted to seven values.
6. Client timeouts: connection 30 seconds, start RPC 60 seconds, workflow execution 25 minutes,
   workflow task 10 seconds. Existing executions retain their previously selected timeouts.
7. WORKER creates an MQ result adapter at the composition root, injects ResponseMessageUtility,
   connects to Temporal once, and calls `worker.run()`. It registers all four activities,
   permits two concurrent activities, and configures a ten-minute graceful shutdown timeout.
   The composition root closes the result adapter on exit. MQ result connection is opened lazily.
8. The workflow runs parsing -> classification -> generation -> publication sequentially.
   Classification receives the enquiry and returns a dictionary. The workflow requires string
   `emotionalType` and accesses `product_code`. Generation receives enquiry text, product code,
   and emotion, loads `{product_code}.json` from `OFTL_AI_PRODUCTCAT` (unset or empty defaults to
   the project `prompts/product_json` folder), and renders the response prompt
   with that serialized product information. This is a direct file lookup, with no vector search.
9. AI calls and publishing run through `asyncio.to_thread`; parser file I/O is synchronous.
   Activity boundaries use JSON-compatible `dict[str, Any]` annotations. Workflow activity imports
   are passed through the sandbox; application configuration/logging must stay out of workflow code.
10. MQGET uses MQGMO_NO_SYNCPOINT: requests are removed before validation or Temporal acceptance.
    Output publication is independent. Failed submissions can lose requests and ambiguous puts
    can produce duplicates. MQ descriptor correlation IDs are not propagated by dispatch.
11. Both application modes inject a fatal MQ error callback. MQ connect, queue-open, receive,
    and publish failures log the error and terminate the entire process with status 1 via
    `os._exit`, including failures on background threads. Empty-queue polling is exempt.
    Fatal exits bypass cleanup and in-flight work; no reconnection or idle publisher health
    check is implemented. Detection occurs when the MQ library reports the failure.

## Workflow outcomes and retry budgets

| Stage | Per-attempt timeout | Total activity budget | Terminal activity error code |
| --- | --- | --- | --- |
| Parsing | 30 seconds | 2 minutes | 8100 |
| Classification | 5 minutes | 9 minutes | 8200 |
| Generation | 5 minutes | 9 minutes | 8300 |
| Publication | 30 seconds | 3 minutes | No recursive error publication |

All policies allow at most five attempts, starting at two seconds with exponential backoff
capped at ten seconds. Total activity budgets can end retries before five attempts occur.
Parser input errors are non-retryable; schema file failures propagate for retry. Unlike the
client, the parser does not configure a format checker.

Success publishes code `0000` and returns the envelope. Terminal processing activity failures
publish the stage code with the decoded original and available partial results, then fail the
workflow with a non-retryable ApplicationError. Exceptions inside workflow processing (including
missing AI fields/type checks) publish `9999`. Cancellation propagates. Publication failure,
workflow termination, and execution timeout do not use another business-error publication path.

Preserve wire spellings: `meta`, `orignalMessage`, `aiAssesment`, `aiGeneratedResponse`.
Response metadata adds responseCode/responseDescription. Error envelopes retain metadata even
without an original object; malformed original metadata stays under orignalMessage. Success
requires original metadata to be a mapping. Missing partial results are omitted from the envelope.

## AI, prompts, and observability

- OpenAIUtility uses Chat Completions, model `default`, configurable sampling/streaming and a
  default 300-second HTTP timeout. callJson checks only that decoded JSON is an object.
- Classification template variables: MESSAGE and CATEGORY. Generation variables: INPUT_MESSAGE,
  INPUT_EMOTION, PRODUCT_INFORMATION. Templates are cached by resolved path per loader.
- `.env.example` selects classification v04 with the supported MESSAGE/CATEGORY placeholders.
  Both configured templates were verified to render. The unversioned classification template
  remains incompatible with the active caller. All 24 application OFTL_* variables are documented
  in README and the example, whose service addresses target Docker Desktop host connectivity.
- Product codes from the model are not validated against a catalogue allowlist or checked for
  path containment before file access. Unknown products fail generation; response schemas are
  not comprehensively enforced. Classification v05 also has inconsistent emotion examples.
- Use workflow.logger in workflows, activity.logger in activities, and centralized Logging in
  other service code. No activity heartbeats or custom progress-to-portal mechanism exists.
  Logger calls are worker logs, not custom workflow history events.
- OpenAI INFO logs contain elapsed time, model/response ID, token usage when available, and
  response character count. DEBUG logs expose rendered prompts and AI responses; MQ settings
  DEBUG logging includes credentials. These remain unresolved data-exposure findings.

## Known gaps and validation baseline (2026-09-11)

- No SQL persistence, durable application backlog, transactional MQ handoff, backout processing,
  or exactly-once output. ALLOW_DUPLICATE permits repeat processing after a closed execution.
- Shared MQ result adapter may be used by concurrent publishing threads; no synchronization is
  implemented. No live concurrency/delivery validation was performed.
- Client reuse-policy parsing lacks a type guard before `.strip()`; unknown names become ValueError.
- The unused legacy orchestration module has been removed. Its parser tests now exercise
  RequestMessageParser; active workflow tests cover sequencing, payloads, budgets, partial
  results, and error publication. Client tests verify start acceptance and all reuse policies.
  Generator tests use the three-string activity interface and mocked product JSON.
- Fresh checks used `.venv/Scripts/python.exe -m`:
  - `ruff check .`: passed.
  - `ruff format --check .`: passed (44 files).
  - `mypy src tests`: passed (37 source files).
  - `pytest -q -p no:cacheprovider --basetemp=<fresh-directory> --cov=src --cov-branch
    --cov-report=term-missing --tb=short`: 118 passed; 87% branch-inclusive coverage.
- Sandboxed pytest runs hit WinError 5 on temporary directories, including a fresh workspace
  directory. The passing full suite ran outside the sandbox using a fresh explicit basetemp.
  This is an environment limitation; no tests were skipped or weakened to bypass it.
- No live MQ, Temporal, AI, database, replay, or concurrency integration was exercised.

## Container startup

The Dockerfile uses Python 3.13 Debian 13 dev/runtime stages and disables uv Python downloads.
The builder runs uv sync --frozen --no-dev --python /usr/bin/python3. Runtime copies the venv,
MQ client, source, pyproject.toml, and prompts, then runs as UID/GID 65532 with readable assets.
CMD invokes src.app.main with explicit OFTL_RUN_MODE (default WORKER), validating CLIENT/WORKER.
It does not invoke uv at startup. Passing an explicit mode also avoids the current app.py
fallback expression using bitwise `|`; that separate native-startup bug remains unchanged.
The build attempt on 2026-09-12 was blocked by Docker Desktop DNS resolution for
production.cloudfront.docker.com before compilation. Full image validation remains pending.

## Environment and commands

The project requires Python 3.12 or newer, while `.python-version` currently selects Python 3.13. Use `uv` and keep `uv.lock` committed.

```powershell
# Create/update the environment from the lockfile
uv sync --dev

# Run the service
uv run customer-enquiry-triage-client
# Run WORKER in another terminal
uv run customer-enquiry-triage-worker

# Run all tests
uv run pytest -q

# Run a focused test
uv run pytest tests/unit/test_settings.py -q

# Run the full quality gate
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=src --cov-branch --cov-report=term-missing
```

Use `uv add <package>` or `uv add --dev <package>` for dependency changes so `pyproject.toml` and `uv.lock` stay synchronized. Do not hand-edit the lockfile.

## Configuration and secrets

- Copy `.env.example` to `.env` for local development. Never commit `.env`, credentials, connection strings, API keys, customer data, or decrypted secret values.
- Configuration keys must be uppercase environment-variable names. Process environment values intentionally override `.env` values.
- Add every new non-secret setting to `.env.example` with a safe example and document whether it is required.
- Validate required settings at startup and fail with a clear error. Do not silently use unsafe production defaults.
- Treat values ending in `_SECRET` as sensitive. Never include their values in logs, exceptions, test snapshots, or queue diagnostics.
- `ConfigLoader.decrypt` is currently a placeholder, not real secret protection. Do not imply otherwise or build security assumptions around it.

## Python and design conventions

- Every new Python file must begin with this module docstring before any imports. Replace the
  description placeholder with a concise, file-specific description. The `Reference` value must
  be the GitHub project URL only; do not link to a file, branch, issue, or non-GitHub page.

  ```python
  """
  Copyright 2026-2028 openfintechlab.com, Inc. All rights reserved.
  Licenses: LICENSE.md
  Description: DESCRIPTION OF THE FILE / CLASS / MODULE
  Reference: URL TO GITHUB PROJECT ONLY
  """
  ```

- Follow the configured Ruff rules and 100-character line length. Format with `uv run ruff format .`.
- Add type annotations to production and test code. The repository uses strict mypy; avoid `Any`, unchecked casts, and blanket `# type: ignore` comments. If suppression is unavoidable, make it narrow and explain why.
- Prefer small modules, explicit dependencies, immutable domain values where practical, and standard-library types.
- Use `pathlib.Path` for filesystem paths and timezone-aware datetimes for persisted or exchanged timestamps.
- Raise specific exceptions and preserve exception chaining with `raise ... from exc`. Translate vendor exceptions at adapter boundaries so vendor types do not leak into domain/application code.
- Keep imports absolute from `src`, as the existing code does. Avoid import-time I/O and mutable module-level state.
- Use the centralized `Logging` abstraction rather than `print` in service code. Use parameterized logging (`Logging.info("Message: %s", value)`) and never log full customer enquiries unless an explicit, approved redaction policy permits it.
- Keep `src/app.py` as the composition root. Runtime clients, repositories, and consumers should be injected into application services rather than constructed inside domain logic.

## Messaging, persistence, and AI boundaries

- Assume IBM MQ delivery is at least once. Handlers must be idempotent, and database records should use a stable message/enquiry identifier to prevent duplicate effects.
- Do not acknowledge/commit an input message until the required durable state and output behavior have succeeded according to the delivery design. Make retry, backoff, dead-letter, and poison-message behavior explicit.
- Preserve correlation IDs across input messages, database history, logs, AI requests, and output messages.
- Define and validate schemas at external boundaries. Reject malformed messages with actionable errors; do not pass unvalidated dictionaries through the application.
- Keep transactions short and make transaction ownership explicit in the application layer. Use SQLAlchemy parameter binding; never interpolate user input into SQL.
- Put timeouts on MQ, database, and HTTP operations. Retries must be bounded and limited to transient failures; avoid retrying validation errors or other permanent failures.
- Treat model output as untrusted input. Require a constrained response shape, validate it before use, and define behavior for timeouts, invalid responses, and unknown classifications.
- Minimize customer data sent to the model. Redact sensitive fields where possible and do not persist prompts/responses beyond the approved audit requirements.

## Testing expectations

- Every behavior change needs tests. Prefer unit tests for domain rules and orchestration, and integration tests for serialization, SQLAlchemy mappings/queries, MQ adapters, and AI-client behavior.
- Tests must be deterministic and must not depend on the developer's `.env`, network, clock, random state, or execution order. Use injected fakes/mocks at external boundaries.
- Reset shared class state such as `ConfigLoader.configurations` and logging configuration when a test changes it. Use `monkeypatch` for process environment changes.
- Test happy paths and relevant failure paths, including malformed input, duplicate delivery, dependency timeout, invalid model output, retry exhaustion, and transaction rollback.
- Do not call real IBM MQ, SQL Server, or AI services from unit tests. Mark and configure integration tests explicitly before adding environment-dependent execution.
- Run the smallest relevant test while iterating, then run the full quality gate before handing off a change.

## Change discipline

- Read the surrounding code and tests before editing. Keep changes narrowly scoped and preserve unrelated user work.
- Update documentation, `.env.example`, schemas, and tests together with behavioral or configuration changes.
- Avoid compatibility shims, speculative abstractions, and broad refactors unless the task requires them.
- Never weaken lint, typing, test, or coverage settings merely to make a change pass. Fix the underlying issue or document a narrowly justified exception.
- Do not commit generated caches, coverage files, virtual environments, local databases, logs, or secrets.
- In the handoff, summarize what changed, list validation commands run, and disclose any failures, skipped checks, assumptions, or operational risks.
