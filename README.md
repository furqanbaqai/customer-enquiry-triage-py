# customer-enquiry-triage-py
Specialized AI Proxy that consumes customer enquiries off IBM MQ, calls an AI endpoint (OpenAI-compatible chat completion) to classify each one, persists tracking/history state in SQL Server, and republishes the classification result to another MQ queue
