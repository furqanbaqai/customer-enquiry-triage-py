# AGENTS.MD

## Purpose and scope

This repository is an early proof of concept for a long-running Python service that will consume customer enquiries from IBM MQ, classify them through an OpenAI-compatible endpoint, store tracking and history data in SQL Server, and publish classification results to an output queue.

The implemented runtime loads configuration, polls IBM MQ, dispatches enquiries to one application worker, validates requests, detects language, calls an OpenAI-compatible endpoint for assessment and response generation, and publishes a combined result envelope to IBM MQ. SQL Server persistence, backout publishing, duplicate detection, application-managed retries, and transaction handling remain unimplemented. Temporal appears only as a TODO. Result publishing is wired into orchestration, but the failure and shutdown paths have known gaps documented below; do not describe this as a production-ready delivery workflow.

These instructions apply to the entire repository. Keep this file current when the architecture, tooling, or required validation changes.

## Repository map

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

1. `src.app.main()` loads `.env` plus process environment values through `ConfigLoader`; process values win.
2. It reads version and description from `pyproject.toml`, builds `IBMMQSettings`, and injects `ResponseMessageUtility(client)` into a shared orchestrator.
3. The MQ adapter connects with `ibmmq.connect`, opens the configured request queue, and polls it with bounded MQGET waits on a managed thread.
4. `dispatch_message` copies the payload up to MQ's reported `DataLength` and submits it to a `ThreadPoolExecutor(max_workers=1)`. The application worker is separate from the MQ polling thread; pending submissions are not bounded.
5. The orchestrator validates UTF-8 JSON against the packaged schema and detects an ISO 639-3 language code, currently used only for logging. It renders `OFTL_AI_PROMPT_1` with `MESSAGE` and `CATEGORY`, parses the AI assessment as a JSON object, and requires a string `emotionalType`. It then renders `OFTL_AI_PROMPT_2` with `INPUT_MESSAGE`, `INPUT_EMOTION`, and `PRODUCT_INFORMATION` (currently the request category), calls the endpoint again, and publishes a response envelope with success code `0000`.
6. Callback exceptions are logged and swallowed. The consumer currently uses `MQGMO_NO_SYNCPOINT`, so delivery is not transactional and failed messages are not automatically rolled back by this code.
7. Registered console signals set a stop event. The `finally` block closes MQ resources before waiting for application workers, creating a risk while queued work is still publishing. A caught `KeyboardInterrupt` or `EOFError` exits with code 1; other exceptions inside the main run block exit with code 99.

The schema requires `meta`, `mobileNumber`, `firstName`, `lastName`, `emailAddress`, `message`, `category`, and `receivedAt`; `customerId` is optional. `meta.refNumber`, `meta.channel`, and `meta.reqIssuedAt` are required, and additional properties are rejected. Although date-time and email formats are declared, the current `jsonschema.validate` call does not supply a format checker, so those formats are annotations rather than enforced validation.

## Context snapshot (2026-09-06)

This snapshot reflects the working tree, including pre-existing edits to `src/app.py` and the sample response filename. Analysis did not change application code or samples.

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
uv run python -m src
# Equivalent installed entry point
uv run customer-enquiry-triage

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
