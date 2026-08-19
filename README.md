# customer-enquiry-triage-py
Specialized AI Proxy that consumes customer enquiries off IBM MQ, calls an AI endpoint (OpenAI-compatible chat completion) to classify each one, persists tracking/history state in SQL Server, and republishes the classification result to another MQ queue

The service consumes requests with IBM MQ's asynchronous MQCB/MQCTL API. Copy `.env.example` to
`.env` and configure the `OFTL_IMQ_*` values before startup. The connection fields are required;
the request, result, and backout queue names have defaults in `.env.example`.

The `ibmmq` package requires the IBM MQ C client runtime. Install the IBM MQ Redistributable Client
and make its libraries available to the process before running `uv run python -m src`.
