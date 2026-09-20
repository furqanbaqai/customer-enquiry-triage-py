# AGENTS.MD

## Purpose and scope

These instructions apply to the entire repository. Keep this file current when architecture,
tooling, or required validation changes. This snapshot replaces the conflicting September 6-10
runtime notes; the source and tests were updated on 2026-09-11 to remove the unused legacy
orchestrator. The active Temporal workflow and registered names remain unchanged.

The application is a Python IBM MQ-to-Temporal customer enquiry triage proof of concept.
The active workflow validates requests, classifies them through an OpenAI-compatible endpoint,
generates a product-informed response, and publishes a response envelope to IBM MQ.
SQL persistence, transactional delivery, backout handling, and application-level deduplication
are not implemented.

## Repository map

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
   and emotion, loads `prompts/product_json/{product_code}.json`, and renders the response prompt
   with that serialized product information. This is a direct file lookup, with no vector search.
9. AI calls and publishing run through `asyncio.to_thread`; parser file I/O is synchronous.
   Activity boundaries use JSON-compatible `dict[str, Any]` annotations. Workflow activity imports
   are passed through the sandbox; application configuration/logging must stay out of workflow code.
10. MQGET uses MQGMO_NO_SYNCPOINT: requests are removed before validation or Temporal acceptance.
    Output publication is independent. Failed submissions can lose requests and ambiguous puts
    can produce duplicates. MQ descriptor correlation IDs are not propagated by dispatch.

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
  remains incompatible with the active caller. All 23 application OFTL_* variables are documented
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
uv run python -m src CLIENT
# Equivalent installed entry point
uv run customer-enquiry-triage CLIENT

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
