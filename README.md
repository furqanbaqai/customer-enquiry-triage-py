# Customer Enquiry Triage

Python service that consumes customer enquiries from IBM MQ, validates them, builds a configured
prompt, and submits it to an OpenAI-compatible classification endpoint.

## Features

- Asynchronous IBM MQ consumption with worker-isolated processing
- JSON Schema validation for incoming enquiries
- Markdown prompt templates with `{{VARIABLE_NAME}}` substitution
- Configurable OpenAI-compatible Chat Completions client
- Environment-based configuration and structured logging

> [!NOTE]
> SQL Server persistence and publishing to result or backout queues are not implemented yet.

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

Update `.env` with your MQ connection, API token, and endpoint values, then start the service:

```powershell
uv run python -m src
```

The installed command is equivalent:

```powershell
uv run customer-enquiry-triage
```

## Configuration

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
| `OFTL_IMQ_QMGR` | Yes | No default |
| `OFTL_IMQ_CHANNEL` | Yes | No default |
| `OFTL_IMQ_LISTENER` | Yes | `1414` in `.env.example` |
| `OFTL_IMQ_USERNAME` | Yes | No default |
| `OFTL_IMQ_PASS` | Yes | No default |
| `OFTL_IMQ_HOST` | Yes | No default |
| `OFTL_IMQ_REQUEST_QUEUE` | No | `AI.CUST.ENQ.TRIAGE.REQUEST.Q` |
| `OFTL_LOG_LEVEL` | No | `INFO` |
| `OFTL_LOG_FORMAT` | No | See `.env.example` |

See [`.env.example`](.env.example) for the complete configuration. Never commit `.env` or real
credentials.

## Prompt templates

Templates are UTF-8 Markdown files with uppercase placeholders such as `{{MESSAGE}}`. Paths are
resolved from the service working directory. Missing files, blank templates, and unresolved
placeholders fail with a clear error.

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
