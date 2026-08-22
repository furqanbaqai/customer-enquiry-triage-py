# customer-enquiry-triage-py
Specialized AI Proxy that consumes customer enquiries off IBM MQ, calls an AI endpoint (OpenAI-compatible chat completion) to classify each one, persists tracking/history state in SQL Server, and republishes the classification result to another MQ queue

The service consumes requests with IBM MQ's asynchronous MQCB/MQCTL API. Copy `.env.example` to
`.env` and configure the `OFTL_IMQ_*` values before startup. The connection fields are required;
the request, result, and backout queue names have defaults in `.env.example`.

The `ibmmq` package requires the IBM MQ C client runtime. Install the IBM MQ Redistributable Client
and make its libraries available to the process before running `uv run python -m src`.

## Prompt templates

Set `OFTL_AI_PROMPT_1` to the path of the Markdown template used for customer enquiry
classification. The repository example uses `prompts/customer_enquiry_triage.md`; paths are
resolved relative to the service process's working directory.

Templates use uppercase `{{VARIABLE_NAME}}` placeholders. Replacement dictionaries are flat (no
nested attribute lookup), extra values are ignored, and `None` renders as an empty string. Prompt
rendering fails clearly if the setting is missing or blank, the file is invalid or empty, or any
placeholders remain unresolved. Templates are read as UTF-8 and only the original template is
cached; rendered prompts containing customer data are never cached or logged.

## OpenAI-compatible endpoint

Set the required `OFTL_OPENAI_URL` and `OFTL_OPENAI_APITOKEN` values. The URL may be either an API
base URL or a full `/chat/completions` URL. Optional request settings and their defaults are
`OFTL_OPENAI_TEMPERATURE=0.1`, `OFTL_OPENAI_TOP_P=0.9`, `OFTL_OPENAI_MAX_TOKENS=200`, and
`OFTL_OPENAI_STREAM=False`. When streaming is enabled, the utility combines the streamed text
chunks into one classification response.
