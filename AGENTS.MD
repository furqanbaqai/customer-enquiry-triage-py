# AGENTS.MD

## Error publication update (2026-09-10)

This update supersedes historical echo-workflow descriptions below. The v2 workflow runs parsing,
classification, generation, and publishing activities. Terminal processing activity failures publish
codes 8100/8200/8300 by stage; unexpected workflow processing exceptions publish 9999. Original
decoded request data and partial results are retained. After publication the workflow fails with a
non-retryable ApplicationError. Cancellation propagates, and publishing failures are not recursively
published. Parser input failures are non-retryable; schema I/O failures propagate for retry.

Error envelopes always contain response metadata, including when no request object is available.
Malformed original metadata stays in orignalMessage for error responses. Success metadata validation
is unchanged. Activity budgets are two minutes for parsing, nine per AI stage, and three for publishing;
each policy allows at most five attempts. New client submissions allow 25 minutes total. Existing
executions retain their original timeout; validate replay compatibility or drain them before rollout.
MQ publication remains susceptible to duplicates after ambiguous failures.

## Purpose and scope

This repository is an early proof of concept for a long-running Python service that will consume customer enquiries from IBM MQ, classify them through an OpenAI-compatible endpoint, store tracking and history data in SQL Server, and publish classification results to an output queue.

The active runtime loads configuration, polls IBM MQ, and dispatches copied message bytes to one application worker. `on_message(**kwargs)` invokes `CustomerEnquiryClient.sendToWorkflow`, which validates the enquiry and executes the v2 Temporal workflow. The v2 workflow currently only echoes its input; the deprecated AI orchestrator remains separate. SQL Server persistence, backout publishing, application-managed retries, and transaction handling remain unimplemented.

These instructions apply to the entire repository. Keep this file current when the architecture, tooling, or required validation changes.

## Repository map

- `src/application/CustomerEnquiryClient.py`: active MQ-to-Temporal submission class; validates schema with formats and executes the v2 workflow using a fresh client/event loop per enquiry.
- `src/application/CustomerEnquiryOrchestrator_v2.py`: Temporal workflow class `CustomerEnquiryOrchaestrator`; currently echoes the input JSON string.
- `src/application/activities/`: decorated async classifier/generator activity placeholders registered by CustomerEnquiryWorker.
- `src/app.py`: application entry point and composition root. Construct and connect dependencies here; keep business rules out of it.
- `src/__main__.py`: support for `python -m src`.
- `src/application/CustomerEnquiryOrchaestrator.py`: request validation, language detection, two AI calls, and result publishing. Preserve the existing filename spelling unless a deliberate rename updates every import.
- `src/application/schema/enquiry-request-v1.0.json`: bundled JSON Schema for incoming messages.
- `src/domain/`: reserved for business entities, value objects, policies, and domain errors; currently empty apart from package initialization. Keep this layer independent of MQ, SQLAlchemy, HTTP clients, and environment configuration.
- `src/infrastructure/ibm_mq.py`: validates IBM MQ settings, manages a bounded MQGET polling thread, and puts explicitly supplied response dictionaries on the configured result queue. Consumer and producer operations use separate connections.
- `src/config/`: configuration loading and validation.
- `src/utilities/`: small cross-cutting helpers such as logging, language detection, prompt loading, and response-envelope generation. Do not turn this into a miscellaneous business-logic package.
- `tests/unit/`: fast, isolated tests.
- `tests/integration/`: tests that exercise adapter boundaries or real/ephemeral services.

Preserve the intended dependency direction: infrastructure depends on application/domain contracts; domain code must not import infrastructure.

## Current runtime behavior

1. `src.app.main(mode=None)` accepts `CLIENT` or `WORKER`; missing or invalid modes exit through argparse. Both valid modes load configuration and display the banner/project information. `WORKER` starts CustomerEnquiryWorker on a persistent event loop for the duration of that worker process. `CLIENT` invokes `_run_mq_client()`. `main_client()` selects CLIENT for the installed client command.
2. The MQ adapter polls the request queue on a managed thread. `dispatch_message` copies the bytes and callback reason/length into submissions to `ThreadPoolExecutor(max_workers=1)`; pending submissions are unbounded.
3. `on_message` logs nonzero callback reasons and returns. Otherwise it invokes `CustomerEnquiryClient.sendToWorkflow(payload)`; exceptions are caught and logged without retry or backout publication.
4. The client decodes UTF-8 JSON and loads/checks the enquiry schema on each message. Draft 2020-12 validation includes email/date-time format checking, supported by the rfc3339-validator dependency. Invalid input raises ValueError; schema-loading and Temporal failures become chained RuntimeError exceptions.
5. Each valid message invokes `asyncio.run()`, creating and closing an event loop. `_async_send_message` connects a fresh Temporal client using `OFTL_AI_TEMPORALURL` (default `localhost:7233`) with a 30-second connection timeout.
6. The client passes the full enquiry as a JSON string to `CustomerEnquiryOrchaestrator.run` from `CustomerEnquiryOrchestrator_v2.py`, on task queue `CUSTOMER.ENQUIRY.REQUEST`. IDs are `CE-{channel.upper()}-{refNumber}`; reuse policy is REJECT_DUPLICATE. Execution timeout is 300 seconds and RPC timeout is 30 seconds. The earlier outer 330-second client wait timeout has been removed.
7. `execute_workflow` waits for completion, serializing message handling through the single application worker. The v2 workflow returns `Processed message: {message}` and invokes no activities. The client logs that result at INFO, exposing the full enquiry.
8. MQGET uses MQGMO_NO_SYNCPOINT, removing messages before validation/Temporal acceptance. Failure can therefore lose a request; duplicate rejection in Temporal does not provide transactional MQ delivery.
9. Shutdown signals set the stop event. The finally block closes MQ resources and then waits for the executor. There is no persistent Temporal client/event-loop lifecycle yet.

The schema requires `meta`, `mobileNumber`, `firstName`, `lastName`, `emailAddress`, `message`, `category`, and `receivedAt`; `customerId` is optional. `meta.refNumber`, `meta.channel`, and `meta.reqIssuedAt` are required, and additional properties are rejected. The active client enforces format checks; the deprecated orchestrator's separate parser does not.

## Temporal worker implementation (2026-09-07)

- `src/application/CustomerEnquiryWorker.py` provides async static `start()`. WORKER mode runs it with asyncio.run in the current process. It connects once using OFTL_AI_TEMPORALURL (default localhost:7233), with a 30-second connection timeout, and registers CustomerEnquiryOrchaestrator plus bound MessageClassifier.classify_message and MessageGenerator.generate_response_message activities on CUSTOMER.ENQUIRY.REQUEST.
- The Worker async context manages polling and shutdown. Ctrl+C cancels the main coroutine; the context shuts down with a 30-second graceful activity period. Connection/worker failures are logged by exception type and wrapped with a chained RuntimeError.
- Activity modules are now message_classifier.py and message_generator.py; both expose decorated async instance methods returning placeholder dictionaries. Registration does not make the echo workflow invoke them.
- src.__init__.main lazily imports src.app, preserving the console entry point while avoiding application/configuration imports during sandbox workflow loading. A sandbox preparation regression test verifies this.
- Validation: 9 worker-focused tests pass; Ruff check passes; modified files are formatted. Full suite: 54 passed, 4 existing failures (two client workflow-ID expectations and two app expectations), 13 temporary-directory permission errors. Mypy retains three union-attr errors in the deprecated orchestrator; full format check retains the existing orchestrator-test formatting issue. No live services were used.

## Context snapshot (2026-09-07)

This snapshot supersedes runtime claims in the historical 2026-09-06 review below.

- User work present at review start: modified `src/application/CustomerEnquiryClient.py` and untracked `src/application/activities/`. Preserve these changes.
- `activities/AC01_MessageClassifier.py` and `AC02_MessageGenerator.py` are empty; their package initializer contains only a docstring. No Temporal Worker registration or SQL persistence implementation was found under src.
- Lifecycle recommendation discussed with the user, not implemented: one application-owned Temporal client on a persistent asyncio loop, with synchronous callers using run_coroutine_threadsafe. A cached client alone is unsuitable while each message uses asyncio.run. Switching execute_workflow to start_workflow is a separate completion-semantics decision, not yet authorized as an implementation change.
- Active INFO result logging exposes enquiry data because the current workflow echoes the full JSON. Existing MQ-settings debug logging can expose credentials; deprecated orchestrator debug logs include prompts/results.
- README still describes a disconnected callback, old workflow ID format, and the removed 330-second wait; treat source and this snapshot as current.
- Validation used the installed virtual environment without live MQ, Temporal, AI, or database calls:
  - `python -m ruff check .`: passed.
  - `python -m ruff format --check .`: one existing failure in tests/unit/test_customer_enquiry_orchestrator.py.
  - `python -m mypy src tests`: three union-attr errors in the deprecated orchestrator at lines 126, 139, and 159.
  - `python -m pytest tests/unit/test_customer_enquiry_client.py -q -p no:cacheprovider --tb=short`: 15 passed, 2 failed. Both expect customer-enquiry-REF-123 but receive CE-WEBSITE-REF-123.
- The full test suite was not rerun during this context refresh. Earlier full-suite results are historical, not a fresh baseline.
- This refresh updates project context only; no application behavior or tests were changed.

## Context snapshot (2026-09-06)

The findings and validation baseline below describe the analysis before callback decoupling. The orchestrator remains in the repository but is no longer called from `src/app.py`. Callback tests now isolate configuration and use normal stop-event completion instead of expecting a caught `KeyboardInterrupt` to return normally. The pre-existing sample response filename change is preserved.

- Response wire keys are `meta`, `orignalMessage`, `aiAssesment`, and `aiGeneratedResponse`. Preserve these existing spellings unless deliberately changing the external contract. Response codes and descriptions are added to copied request metadata; MQ message descriptor correlation IDs are not propagated by the worker dispatch.
- `OpenAIUtility` uses Chat Completions with model name `default`, configurable sampling, timeout, and streaming. `callJson` validates only that parsed JSON is an object; assessment and generated-response schemas are not enforced. Endpoint and prompt configuration are checked when used, rather than comprehensively at startup.
- Prompt templates are cached by resolved path per loader. The repository contains classification variants through v05 and 99 product JSON files. Runtime does not load that product catalogue: response generation receives only the category string as product information. `.env.example` selects the unversioned classification template and the v1.0 response template; it does not establish the developer's private configuration.
- Failure handlers attempt result publication with codes `8100`, `8101`, or `9999`, but parsing failures can reference `enquiry_message` before assignment. Error handlers also dereference an optional response utility without checking it, and publication failures can mask the original error. Schema validation is already translated into `ValueError`, so the outer `ValidationError` handler does not catch normal request-schema failures.
- MQ reads use no syncpoint and output puts are not coordinated with input removal. There is no durable worker backlog, rollback, recovery loop after a fatal polling error, or backout handling. SQLAlchemy is a dependency without a persistence implementation; `src/domain` and `tests/integration` contain only package initializers.
- Debug logging currently includes the MQ settings dataclass (including its password), rendered enquiry prompts, and AI responses. This violates the intended secret/customer-data logging rules below and needs correction before enabling debug logging with real data.
- Classification v05 lists `Angry`, `Frustrated`, and `Calm` as the permitted emotions but shows `Concerned` in its output example. Prompt examples and runtime output validation need alignment.

Validation baseline using the existing Python 3.13.14 virtual environment:

- `.venv\Scripts\ruff.exe check .`: passed.
- `.venv\Scripts\python.exe -m ruff format --check .`: one existing formatting failure in `tests/unit/test_customer_enquiry_orchestrator.py`.
- `.venv\Scripts\python.exe -m mypy src tests`: three `union-attr` errors in orchestration exception handlers (lines 118, 131, 151 at review time).
- `.venv\Scripts\python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing -q`: 27 passed, one failure (`test_main_starts_consumer`, unexpected `SystemExit: 1`), and 13 setup errors caused by denied temporary-directory access. Retrying with `-p no:cacheprovider --basetemp=.pytest_cache/context-review-20260906` still encountered directory access errors. Reported 72% coverage is from this incomplete run, not a clean baseline.
- No live MQ, AI, or database integration was exercised. Existing findings are recorded for follow-up; documentation maintenance does not authorize silently changing runtime behavior.

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
