# AGENTS.MD

## Purpose and scope

This repository is an early proof of concept for a long-running Python service that will consume customer enquiries from IBM MQ, classify them through an OpenAI-compatible endpoint, store tracking and history data in SQL Server, and publish classification results to an output queue.

The currently implemented runtime is narrower: it loads environment configuration, connects to IBM MQ, registers an asynchronous consumer, validates each UTF-8 JSON message against the bundled request schema, logs success or failure, and shuts down gracefully. SQL Server persistence, orchestrated result/backout publishing, duplicate detection, retries, and transaction handling are not implemented yet. The IBM MQ adapter can put an explicitly supplied response on the result queue, but that operation is not yet wired into the orchestration workflow. Do not describe those planned end-to-end capabilities as operational.

These instructions apply to the entire repository. Keep this file current when the architecture, tooling, or required validation changes.

## Repository map

- `src/app.py`: application entry point and composition root. Construct and connect dependencies here; keep business rules out of it.
- `src/__main__.py`: support for `python -m src`.
- `src/application/CustomerEnquiryOrchaestrator.py`: current orchestration skeleton. It parses and validates request messages; the remaining workflow is marked TODO. Preserve the existing filename spelling unless a deliberate rename updates every import.
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
2. It reads version and description from `pyproject.toml`, builds `IBMMQSettings`, and starts `IBMMQClient`.
3. The MQ adapter connects with `ibmmq.connect`, opens the configured request queue, and polls it with bounded MQGET waits on a managed thread.
4. The callback slices the supplied bytes to MQ's reported `DataLength` and invokes a new `CustomerEnquiryOrchestrator`.
5. The orchestrator decodes UTF-8 JSON and validates it against the packaged request schema. It performs no downstream processing after validation.
6. Callback exceptions are logged and swallowed. The consumer currently uses `MQGMO_NO_SYNCPOINT`, so delivery is not transactional and failed messages are not automatically rolled back by this code.
7. Console interrupt signals set a stop event; shutdown joins the polling thread, closes the request queue, and disconnects the queue manager.

The schema requires `meta`, `mobileNumber`, `firstName`, `lastName`, `emailAddress`, `message`, and `receivedAt`; `customerId` is optional. `meta.refNumber`, `meta.channel`, and `meta.reqIssuedAt` are required, and additional properties are rejected. Although date-time and email formats are declared, the current `jsonschema.validate` call does not supply a format checker, so those formats are annotations rather than enforced validation.

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
